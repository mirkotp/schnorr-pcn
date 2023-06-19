import socket
import os
from threading import Thread
from socketserver import StreamRequestHandler, TCPServer
from time import sleep, time
from Node import Node
from charm.core.engine.util import bytesToObject, objectToBytes
from charm.toolbox.ecgroup import ECGroup
from charm.toolbox.eccurve import secp256k1 as curve
from charm.core.math.elliptic_curve import getGenerator

group = ECGroup(curve)
g = getGenerator(group.ec_group)
h = g**42  # h is a public parameter for Pedersen commitments
node_name = os.getenv("NODE_NAME")
is_debug = os.getenv("DEBUG").lower() in ('true', '1', 't')
iterations = int(os.getenv("ITER")) if os.getenv("ITER") is not None else 0


def msg_send(recipient, msg):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect(recipient)
        sock.sendall(objectToBytes(msg, group))


node = Node(group, g, h, node_name, msg_send, is_debug)


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
sleep(1)


initiate = os.getenv("TRANSFER").lower() in ('true', '1', 't') if os.getenv("TRANSFER") else False 
if initiate:
    start_time = time()
    for n in range(iterations):
        amount = int(os.getenv("AMOUNT"))
        path = os.getenv("TRANSFER_PATH").split(",")
        path = list(zip(path, [5000] * len(path)))
        tlock = node.init_transaction(amount, path)
        tlock.acquire()
    print(f"Total execution time: {round(time() - start_time, 2)} seconds")
