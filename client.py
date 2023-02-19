import asyncio, json, argparse
from sys import stdout


class Client(asyncio.Protocol):
    def __init__(self, user: str, message: str, on_con_lost: asyncio.Future, loop: asyncio.AbstractEventLoop):
        """
        Client holds info about: 
        name, last sent message, event loop, timeouted messages. 
        """
        self.message = message
        self.on_con_lost = on_con_lost
        self.user = user
        self.last_message = ""
        self.loop = loop
        self.timeouts = []
        
    def connection_made(self, transport):
        """ 
        Connection to server with basic message
        """
        self.sockname = transport.get_extra_info("sockname")
        self.transport = transport
        msg = {"author": self.user, "event": "init",  "content": "back to the server"}
        self.transport.write((bytes(json.dumps(msg), encoding= "utf-8")))
        
    def connection_lost(self, exc):
        """
        Disconnect from the server.
        Set Future object self.on_con_lost to close transport connection
        """
        print('The server closed the connection')
        self.on_con_lost.set_result(True)

    def data_received(self, data: bytes):
        """
        Data receive handler with callback to process_message function
        """
        if data:
            message = json.loads(data.decode())
            self.process_message(message)

    def process_message(self, message: str|list|dict):
        """
        Message processing callback.
        1. Checks event-type of message to generate message style
        2. Filters messages from the same author as self.user
        3. Ready to work with lists of jsons to save ordering of history messages
        4. Callback parsed message to self.output
        """
        if isinstance(message, dict):
            match message["event"]:
                case "message":
                    data = "{timestamp} | {author}: {content}".format(**message)          
                case "servermsg":
                    data = "{timestamp} | {author} {content}".format(**message)
                case "direct":
                    data = f'{message["timestamp"]} | DIRECT {message["author"]}->{self.user}: {message["content"]}'
                case _:
                    data = "{timestamp} | {author}: {content}".format(**message)

            if message["author"] == self.user:
                data = f'{message["content"]}'
                stdout.write(data + '\n')
            else:       
                review = "{content}".format(**message)
                self.output(data.strip(), review.strip())

        elif len(list(message)) > 0:
            history = list(message)
            for m in history:
                self.process_message(m)

    def send(self, data: str|list|dict):
        """
        Parses message before sending it to the server.
        Options: 
        1) message to all; 
        2) direct message to user; 
        3) timeout sending or kill TimerHandling objects on client side.
        """
        if data and self.user:
            self.last_message = data
            if data.startswith("direct:"):
                msg = {"author": self.user, "event": "direct", "content": data.replace("direct:", "")}
            else:
                msg = {"author": self.user, "event": "message",  "content": data}
            
            delay = False
            cont = msg["content"].split(" ")
            for i in range(len(cont)):
                if cont[i].startswith("timeout:"):
                    delay = True
                    if cont[i].endswith("kill"):
                        for handler in self.timeouts:
                                handler.cancel()
                        self.timeouts.clear()
                        print("All timeouts have been cancelled.")
                        break
                    else:
                        timeout = int(cont[i].replace("timeout:", ""))
                        msg["content"] = " ".join(msg["content"].replace(cont[i], "", 1).split())
                        handler = self.loop.call_later(timeout, self.write, msg)
                        self.timeouts.append(handler)
            if not delay:
                self.write(msg)
    
    def write(self, msg: str|list|dict):
        """
        Callback func that writes to the server.
        """
        self.transport.write(bytes(json.dumps(msg), encoding = "utf-8"))

    async def getmsgs(self, loop: asyncio.AbstractEventLoop):
        """
        Async Task for always available user input-line in console.
        Solves the problem of blocked input while reading chat. 
        """
        self.output = self.stdoutput
        self.output("Connected to {0}:{1}\n".format(*self.sockname), "")
        while True:
            msg = await loop.run_in_executor(None, input)
            if msg != "":
                self.send(msg)

    def stdoutput(self, data: str|list|dict, review: str|list|dict):
        """
        Writes last message to the client output if it's not ours.
        """
        if self.last_message == review:
            return
        else:
            stdout.write(data + '\n')

async def main():
    """
    Runs with console args: user, addr, port.
    Runs Client in current event loop.
    Runs input Task in current event loop.
    Awaits until connection is lost.
    """
    loop = asyncio.get_running_loop()

    on_con_lost = loop.create_future()
    message = args["user"] + "connected"

    client = Client(args["user"], message, on_con_lost, loop)

    transport, protocol = await loop.create_connection(
        lambda: client,
        args["addr"], args["port"])
    
    loop.create_task(client.getmsgs(loop))
    
    try:
        await on_con_lost
    finally:
        transport.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Client settings")
    parser.add_argument("--user", default="User", type=str)
    parser.add_argument("--addr", default="127.0.0.1", type=str)
    parser.add_argument("--port", default=8000, type=int)
    args = vars(parser.parse_args())

    asyncio.run(main())