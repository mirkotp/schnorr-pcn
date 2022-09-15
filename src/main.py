import os
from threading import Thread
from socketserver import StreamRequestHandler, TCPServer
from time import sleep
from Node import Node
from charm.core.engine.util import bytesToObject
from charm.toolbox.ecgroup import ECGroup
from charm.toolbox.eccurve import secp256k1

group = ECGroup(secp256k1)
g = group.deserialize(bytes(os.getenv('GENERATOR'), encoding='utf-8'))

node_name = os.getenv('NODE_NAME')
node = Node(group, g, node_name)

class Handler(StreamRequestHandler):
    def handle(self):
        data = self.rfile.readline().strip()
        node._msg_receive(bytesToObject(data, group))

def launch_server():
    with TCPServer((node_name, 5000), Handler) as server:
        addr = server.socket.getsockname()
        print(f"{node_name}: Starting server on {server.socket.getsockname()}")
        node.address = addr
        server.serve_forever()

t = Thread(target=launch_server)
t.start()

if(os.getenv('TRANSFER') == "1"):
    sleep(2)
    amount = int(os.getenv('AMOUNT'))
    path = os.getenv('TRANSFER_PATH').split(',')
    path = list(zip(path, [5000] * len(path)))
    node.init_transaction(amount, path)
