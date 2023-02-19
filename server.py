import asyncio
import argparse
import datetime
import json
from queue import Queue


class Server(asyncio.Protocol):
    def __init__(self, short_history: asyncio.Queue,
                       long_history: list,
                       loop: asyncio.BaseEventLoop,
                       connections = dict(), users = dict()):
        """
        Server holds:
        1) map: Transport -> Author (self.connections)
        2) map: Author -> [Transports, last message timestamp]
        3) Current peer Transport-info
        4) Current Event Loop
        5) Short history: asyncio.Queue(maxsize = 20)
        6) Long history: list of all messages for this session
        """
        self.connections = connections
        self.users = users
        self.peername = ""
        self.serverName = "Main Chat Server"

        self.loop = loop
        self.short_history = short_history
        self.long_history = long_history

    def connection_made(self, transport):
        """
        Handles current connection
        """
        self.peername = transport.get_extra_info("sockname")
        self.transport = transport

    def connection_lost(self, exc):
        """
        1. Removes disconnected peer from map: Transport->Author
        2. Removes disconnected peer from map: Authors -> [Transports, ...]
        3. Reports about disconnection to all peers
        """
        err = f'{self.connections[self.transport]} disconnected'

        user = self.connections[self.transport]
        self.users[user][0].remove(self.transport)

        if isinstance(exc, ConnectionResetError):
            self.connections.pop(self.transport, None)
        else:
            print(exc)

        message = self.make_msg(err, "[Server]", "servermsg", user)
        print(err)
        for connection in self.connections:
            connection.write(message)


    def broadcast(self, msg: bytes, connections: dict, 
                  current_transport: asyncio.BaseTransport|None = None):
        """
        Callback to broadcast messages to connections.
        """
        for connection in connections:
            if not connection is current_transport:
                connection.write(msg)

    def data_received(self, data):
        """
        1. Registers a new Author in maps
        2. Registers double connections to the same Author
        3. Reports about returning Authors: "UserName back to server"
        4. Sends Author/server messages/reports to all registered Authors if event: "message"|"servermsg"
        5. Sends direct messages p2p if event: "direct" 
        * Appends all actions to short and long history
        """
        if data:
            dData = json.loads(data.decode("utf-8"))

            # Authorization
            if not dData["author"] in self.users:
                self.connections[self.transport] = dData["author"]
                self.users[dData["author"]] = [[self.transport,], None]
                self.send_history(self.transport, h_type = "short")

                msg_txt = f'{dData["author"]} connected to {self.serverName}'
                print(msg_txt)
                msg = self.make_msg(msg_txt, "[Server]", "servermsg", dData["author"])
                self.broadcast(msg, self.connections, self.transport)

            # Sync 2 profiles with Connections and Users
            elif self.transport not in self.users[dData["author"]][0] and \
            self.connections[self.users[dData["author"]][0][0]] == dData["author"]:
                self.users[dData["author"]][0].append(self.transport)
                self.connections[self.transport] = dData["author"]
                self.send_history(self.transport, h_type = "short")

            # Second connection
            elif not self.transport in self.connections or \
            self.connections[self.transport] != dData["author"]:
                self.users[dData["author"]][0].append(self.transport)
                self.connections[self.transport] = dData["author"]
                self.send_history(self.transport, h_type = "long")

                msg_txt = f'{dData["content"]}'
                msg = self.make_msg(msg_txt, dData["author"], "message")
                self.broadcast(msg, self.connections, self.transport)

            elif dData["event"] == "message":
                msg_txt = f'{dData["content"]}'
                print(f'{dData["author"]}: {msg_txt}')
                msg = self.make_msg(msg_txt, dData["author"], "message")
                self.broadcast(msg, self.connections, self.transport)
            
            elif dData["event"] == "direct":
                directUser = dData["content"].split(" ")[0]
                msg_txt = f'{dData["content"].replace(directUser, "", 1)}'
                if directUser in self.users:
                    print(f'direct {dData["author"]} -> {directUser}: {msg_txt}')
                    msg = self.make_msg(msg_txt, dData["author"], "direct", None, directUser)
                    for transport in self.users[directUser][0]:
                        transport.write(msg)
                    for transport in self.users[dData["author"]][0]:
                        if transport != self.transport:
                            msg = self.make_msg(f'direct:{directUser} ' + dData["content"], 
                                                dData["author"], "direct", None, directUser)
                            transport.write(msg)

                else:
                    msg_txt = f'Failed {dData["author"]} -!> {directUser}. There is no such user!'
                    print(f'Failed {dData["author"]} -!> {directUser}')
                    msg = self.make_msg(msg_txt, "[Server]", "direct", dData["author"], None)
                    self.broadcast(msg, self.users[dData["author"]][0], self.transport)

        else:
            usr = self.connections[self.transport]
            msg = self.make_msg("Empty message error.",
                                "[Server]", "servermsg", usr)
            self.broadcast(msg, self.users[usr][0])
        

    def send_history(self, transport, h_type: str):
        """
        Sends history for new/returned Authors.
        For new Authors short history used by default (last 20 messages).
        For returned Authors long history used by default (all messages since last sent).
        Messages are grouped to "list of jsons" and sent serialized.  
        """
        to_send = []
        author = self.connections[transport]
        
        match h_type:
            case "short":
                for _ in range(self.short_history.qsize()):
                    message = self.short_history.get_nowait()
                    if message["event"] == "direct" and author in message["directUser"]:
                        to_send.append(message)
                        self.short_history.put_nowait(message)
                    elif message["event"] == "direct":
                        self.short_history.put_nowait(message)
                        continue
                    else:
                        to_send.append(message)
                        self.short_history.put_nowait(message)
        
            case "long":
                last = self.users[author][1]
                start_index = 0
                if last is not None:
                    for i, message in enumerate(self.long_history):
                        if message["timestamp"] == last:
                            start_index = i + 1
                            break
                if start_index < len(self.long_history) - 1:
                    for message in self.long_history[start_index:]:
                        if message["event"] == "direct" and author in message["directUser"]:
                            to_send.append(message)
                        elif message["event"] == "direct":
                            continue
                        else:
                            to_send.append(message)

        transport.write((bytes(json.dumps(to_send, indent=2), encoding = "utf-8")))


    def make_msg(self, message: str, author: str, event: str, user: str|None = None, directUser: str|None = None):
        """
        Callback to "jsonize" a message the right way.
        Appends content, author_name, current timestamp, event_type 
        and some inner info to handle mailing addresses.
        Here is the point of message writing to short/long history as dict-object. 
        """
        msg = dict()
        msg["content"] = message
        msg["author"] = author
        time = datetime.datetime.utcnow()
        # MSK UTC+3
        msg["timestamp"] = "{hour}:{minute}:{sec}".format(hour=str(time.hour + 3).zfill(2),
                                                          minute=str(time.minute).zfill(2),
                                                          sec=str(time.second).zfill(2))

        msg["event"] = event if event else "message" 

        if msg["event"] == "direct" and directUser is not None:
            msg["directUser"] = [author, directUser]
        
        if msg["event"] == "direct" and user is not None:
            msg["directUser"] = [user]
        
        if user is not None:
            author = user

        self.users[author][1] = msg["timestamp"]
        self.append_to_history(msg)
    
        return json.dumps(msg).encode()

    def append_to_history(self, msg: dict) -> None:
        """
        Callback to append message to history
        """
        try:
            self.short_history.put_nowait(msg)
        except asyncio.QueueFull:
            self.short_history.get_nowait()
            self.short_history.put_nowait(msg)
        
        self.long_history.append(msg)
        

async def main():
    """
    Runs with console args: host, port, hsize.
    Runs Server in current event loop.
    Runs short history Queue in current event loop.
    """
    loop = asyncio.get_running_loop()

    short_history = asyncio.Queue(maxsize = args.hsize)
    long_history = []

    serve = Server(short_history, long_history, loop)

    server = await loop.create_server(
        lambda: serve,
        args.host, args.port)

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Write host and port to connect")
    parser.add_argument("-n", "--host", type=str, default = "127.0.0.1", help = "Default: 127.0.0.1")
    parser.add_argument("-p", "--port", type=int, default = 8000, help = "Default: 8000")
    parser.add_argument("-s", "--hsize", type=int, default = 20, help = "History Size. Default: 20")
    args = parser.parse_args()

    asyncio.run(main())
    

