from Node import Node
from charm.toolbox.ecgroup import ECGroup, G, ZR
from charm.toolbox.eccurve import secp256k1

N_NODES = 5

group = ECGroup(secp256k1)
g = group.random(G)

skeys = []
for i in range(N_NODES):
    skeys.append(group.random(ZR))

nodes = []
for i in range(N_NODES):
    pkL = g ** (skeys[i-1] * skeys[i]) if i > 0 else None
    pkR = g ** (skeys[i] * skeys[i+1]) if i < N_NODES-1 else None
    nodes.append(Node(group, g, f"node_{i}", skeys[i], pkL, pkR))

nodes[0].init_transaction(50, nodes[1:])