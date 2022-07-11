#property copyright "PVLTMK @ Splinex Team Inc."
#property link      "https://www.mql5.com"
#property version   "1.00"
#property strict

#define SOCKET_LIBRARY_USE_EVENTS
#include <socket-library-mt4-mt5.mqh>

input string   SERVER_HOST = "111.222.333.4444"; // Server host
input ushort   SERVER_PORT = 99999;              // Server port
input string   BROKER      = "ICM";              // Broker canonical name

ushort TIMER_FREQUENCY_MS     = 1;
ushort PING_DELAY_SEC         = 1;
ushort ACCOUNT_INFO_DELAY_SEC = 5;
ushort CONNECTION_TIMEOUT_SEC = 5;

ClientSocket * client              = NULL;
datetime       lastPingOutTime     = TimeLocal();
datetime       lastPingInTime      = TimeLocal();
datetime       lastAccountInfoTime = TimeLocal();

struct Candle {
   double t;
   double o;
   double h;
   double l;
   double c;
   double spread_cumsum;
};

Candle t25;
Candle t50;
Candle t100;
Candle t200;

int t25s  = 0;
int t50s  = 0;
int t100s = 0;
int t200s = 0;

int OnInit() {
   EventSetMillisecondTimer(TIMER_FREQUENCY_MS);
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason) {
   EventKillTimer();
   if(client) {
      delete client;
   }
}

string CandleProcess(MqlTick &tick, Candle &c, int &size, int max_size){
   double price  = (tick.ask + tick.bid) / 2;
   double spread = tick.ask - tick.bid;

   if (size == 0) {
      c.t = tick.time_msc;
      c.o = price;
      c.h = price;
      c.l = price;
      c.spread_cumsum = 0;
   }
   c.spread_cumsum += spread;

   if (price > c.h){
      c.h = price;
   }

   if (price < c.l){
      c.l = price;
   }

   c.c = price;

   size++;

   string msg = "";

   if (size == max_size){
      Print("T", max_size, BROKER, _Symbol, " t: ", c.t, " o: ", c.o, " h: ", c.h, " l: ", c.l, " c: ", c.c, " s: ", c.spread_cumsum/size);
      msg = "t,"+ BROKER +"," +
            _Symbol + "," +
            max_size + "," +
            c.t + "," +
            c.o + "," +
            c.h + "," +
            c.l + "," +
            c.c+"," +
            c.spread_cumsum/size + "," +
            tick.time_msc + "\r\n";
      size = 0;
   }

   return msg;
}

void OnTick() {
   MqlTick tick;
   if (SymbolInfoTick(_Symbol, tick)){
      string m25  = CandleProcess(tick, t25,  t25s,  25);
      string m50  = CandleProcess(tick, t50,  t50s,  50);
      string m100 = CandleProcess(tick, t100, t100s, 100);
      string m200 = CandleProcess(tick, t200, t200s, 200);
      if (client) {
        client.Send(m25+m50+m100+m200);
      }
   } else {
      Print("Get tick error " + GetLastError());
   }
}

void OnTimer() {
   if(!client) {
      Print("Connect to socket server!");
      client = new ClientSocket(SERVER_HOST, SERVER_PORT);
      lastPingInTime = TimeLocal();
   }

   // Do ping
   if((double)(TimeLocal() - lastPingOutTime) >= PING_DELAY_SEC) {
      client.Send("p\r\n");
      lastPingOutTime = TimeLocal();
   }

   // Receive cmd
   string strCommand;
   while (true) {
      strCommand = client.Receive("\r\n");
      if (strCommand != "") {
         lastPingInTime = TimeLocal();
      }
      if (strCommand == "") {
         break;
      }
   }

   // Check timeout
   if((double)(TimeLocal() - lastPingInTime) > CONNECTION_TIMEOUT_SEC)
     {
      Print("Socket disconnected!");
      delete client;
      client = NULL;
     }
  }