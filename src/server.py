from multiprocessing import Process, Queue
from pymongo import MongoClient, IndexModel
import numpy as np
import traceback
import datetime
import socket
import time
import pika
import pytz
import os

TIMEOUT_SEC = 5
BLACKLIST = {'195.54.161.250', '92.255.85.135', '192.241.207.168', '192.241.209.28'}

MONGO_URI = os.environ.get('MONGO_URI')


class TimeoutException(Exception):
    pass


class Connection(Process):
    def __init__(self, conn, mongo_candle_saver_q: Queue):
        Process.__init__(self)
        self.daemon = True
        self.conn = conn
        self.last_message_time = time.time()
        self.receive_data_buffer = b''
        self.rabbit_connection = None
        self.rabbit_channel = None
        self.mongo_candle_saver_q = mongo_candle_saver_q
        self.callback = {
            'p': self.__ping_callback,
            't': self.__candle_callback,
        }

    def __recvall(self):
        while self.last_message_time + TIMEOUT_SEC > time.time():
            try:
                if b'\r\n' in self.receive_data_buffer:
                    index = self.receive_data_buffer.index(b'\r\n')
                    msg = self.receive_data_buffer[:index].decode('utf-8')
                    self.receive_data_buffer = self.receive_data_buffer[len(msg)+2:]
                    self.last_message_time = time.time()
                    msg_s = msg.split(',')
                    return msg_s[0], msg_s[1:]
                else:
                    part = self.conn.recv(4096)
                    if part == b'':
                        raise socket.timeout
                    self.receive_data_buffer += part
                    self.last_message_time = time.time()
            except socket.timeout:
                raise TimeoutException()
        raise TimeoutException()

    def __send(self, msg):
        msg = f'{msg}\r\n'.encode('utf-8')
        try:
            self.conn.send(msg)
        except Exception as e:
            print(e, flush=True)

    def __ping_callback(self, args):
        self.__send(f'p')

    def __candle_callback(self, args):
        print(f'[{datetime.datetime.now()}] {args}', flush=True)
        broker = args[0]
        ticker = args[1]
        t_size = args[2]
        """                    t               o              h                 l                c            spread            send ts  """
        candle = np.array([float(args[3]), float(args[4]), float(args[5]), float(args[6]), float(args[7]), float(args[8]), float(args[9])])

        try:
            self.mongo_candle_saver_q.put((broker, ticker, t_size, candle))
            self.rabbit_channel.basic_publish(exchange='ticks', routing_key=f'{broker} {ticker} {t_size}', body=candle.tobytes())
        except Exception as e:
            print(f'Pika needs to reconnect [{broker}][{ticker}][{t_size}]. (connector haven\'t been used very long time)', flush=True)
            # Try to reconnect
            try:
                self.__rabbit_connect()
                print(f'Pika resend [{broker}][{ticker}][{t_size}]', flush=True)
                self.rabbit_channel.basic_publish(exchange='ticks', routing_key=f'{broker} {ticker} {t_size}', body=candle.tobytes())
            except Exception as e:
                traceback.print_exc()
                print(e, flush=True)
        # # WINTER  - 3
        # # SUMMER  - 2                                                 here
        # print(f'Receive delay {(time.time() * 1000 - (float(args[9]) - 3 * 60 * 60 * 1000)) / 1000}', flush=True)

    def __rabbit_connect(self):
        if self.rabbit_connection and self.rabbit_connection.is_open:
            try:
                print('Pika close old connection', flush=True)
                self.rabbit_channel.close()
            except Exception as e:
                traceback.print_exc()
                print('Pika close connection exception', flush=True)

        print('Pika create new connection', flush=True)
        self.rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(host='host.docker.internal', port=5672))
        self.rabbit_channel = self.rabbit_connection.channel()
        self.rabbit_connection.sleep(1)
        self.rabbit_channel.exchange_declare(exchange=f'ticks', exchange_type='direct')

    def run(self):
        self.__rabbit_connect()

        while True:
            try:
                cmd, args = self.__recvall()
                self.callback[cmd](args)
            except TimeoutException as te:
                print('Client has gone away. Close connection', flush=True)
                try:
                    self.conn.shutdown(socket.SHUT_RDWR)
                    self.conn.close()
                except Exception as e:
                    print(e, flush=True)
                break


class CandleRealtimeSaver(Process):
    def __init__(self, q: Queue):
        Process.__init__(self)
        self.daemon = True
        self.q = q
        self.mongo = None
        self.broker_timezone_offset = {
            'Alpari': 7,
            'ICM': 7,
            'FXOpen': 7,
            'Rithmic': 0,
        }
        self.broker_terminal_timezone = {
            'Alpari': pytz.timezone('US/Eastern'),
            'ICM': pytz.timezone('US/Eastern'),
            'FXOpen': pytz.timezone('US/Eastern'),
            'Rithmic': pytz.UTC,
        }
        self.__collections_checked = set()
        self.__index_for_check = [IndexModel([('dt', -1)], unique=True)]

    def run(self):
        self.mongo = MongoClient(MONGO_URI)
        while True:
            try:
                broker, ticker, t_size, candle = self.q.get()
                candle = candle.tolist()

                terminal_timezone = self.broker_terminal_timezone[broker]
                timezone_offset   = self.broker_timezone_offset[broker]

                d = terminal_timezone.localize(datetime.datetime.fromtimestamp(candle[0] / 1000)  - datetime.timedelta(hours=timezone_offset), is_dst=None)
                d_send = terminal_timezone.localize(datetime.datetime.fromtimestamp(candle[-1] / 1000) - datetime.timedelta(hours=timezone_offset), is_dst=None)
                print(f'{d} {d_send} {datetime.datetime.now(tz=pytz.UTC)}', flush=True)
                print(f'Receive delay {datetime.datetime.now(tz=pytz.UTC)-d_send}', flush=True)
                hm = d.astimezone(pytz.timezone('US/Eastern')).hour + d.astimezone(pytz.timezone('US/Eastern')).minute / 60
                if f'{broker}_{ticker}_{t_size}' not in self.__collections_checked:
                    print(f'check index for database: tr_ticks_mt5_{broker} collection: {ticker}_T{t_size}', flush=True)
                    self.__create_index(f'tr_ticks_mt5_{broker}', f'{ticker}_T{t_size}')
                    self.__collections_checked.add(f'{broker}_{ticker}_{t_size}')

                self.mongo[f'tr_ticks_mt5_{broker}'][f'{ticker}_T{t_size}'].insert_one({
                    'candle': candle[1:-2] + [0, hm, candle[-2]],
                    'dt': d
                })
            except Exception as e:
                traceback.print_exc()
                print(e, flush=True)
                time.sleep(2)

    def __create_index(self, database, collection):
        self.mongo[database][collection].create_indexes(self.__index_for_check)


class Server(object):
    def __init__(self, hostname, port):
        self.hostname = hostname
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.socket.bind((self.hostname, self.port))
        self.socket.listen(100)

    def start(self):
        print("Wait for incoming connections", flush=True)
        while True:
            conn, address = self.socket.accept()
            conn.settimeout(TIMEOUT_SEC)
            if address[0] in BLACKLIST:
                print(f'[REJECT] IP address from black list - {address}', flush=True)
                continue
            print(f"Connected {address}", flush=True)
            connection = Connection(conn, candle_saver_q)
            connection.start()


candle_saver_q = Queue()

if __name__ == '__main__':
    crs = CandleRealtimeSaver(candle_saver_q)
    crs.start()
    server = Server(hostname="0.0.0.0", port=9999)
    server.start()
