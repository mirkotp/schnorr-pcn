from Node import Node
from charm.toolbox.ecgroup import ECGroup, G, ZR
from charm.toolbox.eccurve import secp256k1

N_NODES = 5

group = ECGroup(secp256k1)
g = group.random(G)

nodes = []
for i in range(N_NODES):
    nodes.append(Node(group, g, f"node_{i}"))

nodes[0].init_transaction(50, nodes[1:])