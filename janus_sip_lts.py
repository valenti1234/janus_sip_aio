import argparse
import asyncio
import logging
import random
import string
import time
import aiohttp
import json
import sys

from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.contrib.media import MediaPlayer, MediaRecorder


pcs = set()

def LINE():
    return sys._getframe(1).f_lineno

with open("config/default.json", "r") as jsonfile:
    cfg = json.load(jsonfile)
    print("Read successful")
    
print(LINE(),"config --->",json.dumps(cfg, indent=4))    


def transaction_id():
    return "".join(random.choice(string.ascii_letters) for x in range(12))


class JanusPlugin:
    def __init__(self, session, url):
        self._queue = asyncio.Queue()
        self._session = session
        self._url = url

    async def send(self, payload):
        #print(LINE(),"send --->",json.dumps(payload, indent=4))
        message = {"janus": "message", "transaction": transaction_id()}
        message.update(payload)
        
        async with self._session._http.post(self._url, json=message) as response:
            data = await response.json()
            assert data["janus"] == "ack"
         #   print(LINE(),"post data",data)
            return data


class JanusSession:
    def __init__(self, url):
        self._http = None
        self._poll_task = None
        self._plugins = {}
        self._root_url = url
        self._session_url = None
        

    async def attach(self, plugin_name: str,event_fnc) -> JanusPlugin:
        self.event_fnc = event_fnc
        message = {
            "janus": "attach",
            "plugin": plugin_name,
            "transaction": transaction_id(),
        }
        async with self._http.post(self._session_url, json=message) as response:
            data = await response.json()
            assert data["janus"] == "success"
            plugin_id = data["data"]["id"]
            plugin = JanusPlugin(self, self._session_url + "/" + str(plugin_id))
            self._plugins[plugin_id] = plugin
            #print(62,json.dumps(message, indent=4),json.dumps(response, indent=4));
            return plugin

    async def call(self,plugin):
#        print(LINE(),"call *******",player)
        self.pc = RTCPeerConnection()
        pcs.add(self.pc)

        @self.pc.on("track")
        async def on_track(track):
            print(LINE(),"Track received", track)
            #if track.kind == "video":
            #    recorder.addTrack(track)
            #if track.kind == "audio":
            #    recorder.addTrack(track)
        
        # configure media
        media = {"audio": False, "video": False}
        
        if player and player.audio:
            self.pc.addTrack(player.audio)
            media["audio"] = True
        
        if player and player.video:
            media["video"] = True
            self.pc.addTrack(player.video)
        else:
            media["video"] = False
            self.pc.addTrack(VideoStreamTrack())
        
        # send offer
        await self.pc.setLocalDescription(await self.pc.createOffer())
        request = {"request": "call","uri":"sip:1004@omni3.apimobile.com:35060"}
        request.update(media)
        print(LINE(),"----------> UPDATE MEDIA", media)
        response = await plugin.send(
            {
                "body": request,
                "jsep": {
                    "sdp": self.pc.localDescription.sdp,
                    "trickle": False,
                    "type": self.pc.localDescription.type,
                },
            }
        )        
        return response

    async def startmedia(self,plugin,data):
        print(LINE(),"startmedia *******",json.dumps(data, indent=4))
        
        await self.pc.setRemoteDescription(
            RTCSessionDescription(
                sdp=data["jsep"]["sdp"], type=data["jsep"]["type"]
            )
        )
#        print(LINE(),"startmedia *******")

    async def register(self,plugin):
#        print(LINE(),"register *******")
        response = await plugin.send(
            {
                "body": {
                    "proxy" : "sip:omni3.apimobile.com:35060",
                    "server":"sip:omni3.apimobile.com:35060",
                    "request": "register",
                    "sipserver": "sip:omni3.apimobile.com:35060",
                    "username": "sip:1007@omni3.apimobile.com",
                    "secret": "00123400",
                    "authuser": "1007",
                    "displayname" : "Bob",
                    "sips" : False
                }
            }
        )
        return response

    async def create(self):
        self._http = aiohttp.ClientSession()
        message = {"janus": "create", "transaction": transaction_id()}
        async with self._http.post(self._root_url, json=message) as response:
            data = await response.json()
            assert data["janus"] == "success"
            session_id = data["data"]["id"]
            self._session_url = self._root_url + "/" + str(session_id)
            #print(73,json.dumps(message, indent=4),json.dumps(response, indent=4));

        self._poll_task = asyncio.ensure_future(self._poll())

    async def destroy(self):
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None

        if self._session_url:
            message = {"janus": "destroy", "transaction": transaction_id()}
            async with self._http.post(self._session_url, json=message) as response:
                data = await response.json()
                assert data["janus"] == "success"
            self._session_url = None

        if self._http:
            await self._http.close()
            self._http = None

    async def _poll(self):
        while True:
            params = {"maxev": 1, "rid": int(time.time() * 1000)}
#            print(LINE(),"*******","GET wait")
            async with self._http.get(self._session_url, params=params) as response:
                data = await response.json()
 #               print(LINE(),"*******")
 #               print(LINE(),json.dumps(data, indent=4),data["janus"]);

                if data["janus"] == "event":
                    plugin = self._plugins.get(data["sender"], None)
  #                  print(LINE(),"*******",plugin)
                    #event = data["plugindata"]["data"]["result"]["event"]
                    await self.event_fnc(data,plugin)
                        
 

async def eventcall(data,plugin):
    print(LINE(),"eventcall",data,plugin)
    event = data["plugindata"]["data"]["result"]["event"]
    
    if event == "registered" :
        response =await session.call(plugin)
        print(LINE(),"response",response)
        
    if event == "progress" :
        response =await session.startmedia(plugin,data)
 #       print(LINE(),"response",response)


async def run(player, recorder, session, args):
    await session.create()
    # join sip
    plugin = await session.attach("janus.plugin.sip",eventcall)
    
    response =await session.register(plugin)
    print(LINE(),"response",response)
    
    if args.time :
        seconds=int(args.time)
    else:
        seconds=60
        
    print(LINE(),"!run loop begin!",seconds)        
    await asyncio.sleep(seconds)
    print(LINE(),"!run loop end!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Janus")
    parser.add_argument("url", help="Janus root URL, e.g. http://localhost:8088/janus")
    parser.add_argument("--play-from", help="Read the media from a file and sent it."),
    parser.add_argument("--record-to", help="Write received media to a file."),
    parser.add_argument("--verbose", "-v", action="count")
    parser.add_argument("--time", "-t", help="max time to run in secs")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    # create signaling and peer connection
    session = JanusSession(args.url)
 
    # create media source
    if args.play_from:
        player = MediaPlayer(args.play_from)
    else:
        player = None

    # create media sink
    if args.record_to:
        recorder = MediaRecorder(args.record_to)
    else:
        recorder = None


    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(
            run(player=player, recorder=recorder, session=session,args=args)
        )
    except KeyboardInterrupt:
        pass
    finally:
        if recorder is not None:
            loop.run_until_complete(recorder.stop())
        loop.run_until_complete(session.destroy())

        # close peer connections
        coros = [pc.close() for pc in pcs]
        loop.run_until_complete(asyncio.gather(*coros))
