import socket
import socketserver
from time import sleep
from Node import Node
from charm.toolbox.ecgroup import ECGroup, G
from charm.toolbox.eccurve import secp256k1
from charm.core.engine.util import objectToBytes, bytesToObject
from multiprocessing import Process, Array

N_NODES = 5

group = ECGroup(secp256k1)
g = group.random(G)

addrs = [''] * N_NODES
ports = Array('i', [0] * N_NODES)
def start_node(i):
    n = Node(group, g, f"node_{i}")
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            data = self.rfile.readline().strip()
            n._msg_receive(bytesToObject(data, group))

    with socketserver.TCPServer(('', 0), Handler) as server:
        addr = server.socket.getsockname()
        ports[i] = addr[1]
        print(f"node_{i}: Starting server on {server.socket.getsockname()}")
        n.address = addr
        server.serve_forever()

for i in range(N_NODES):
    p = Process(target=start_node, args=(i,))
    p.start()


sleep(1)
nodes = list(zip(addrs, ports))
print(nodes)

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.connect(nodes[0])
    sock.sendall(objectToBytes({
        "action": "send",
        "__expected_state__": "_WAIT_SETUP",
        "amount": 53,
        "path": nodes[1:]
    }, group))

p.join()