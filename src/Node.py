from abc import ABC, abstractmethod
import socket
from threading import Lock
from charm.core.engine.util import objectToBytes
from charm.toolbox.ecgroup import ZR

class Node():
    _state = None
    _lock  = None
    transaction_fee = 1

    leftNode = ('', 0)
    rightNode = ('', 0)

    # Protocol variables
    pkL = 0           # Shared key with left node
    pkR = 0           # Shared key with right node
    SI = (0, 0, 0)    # State
    SL = (0, 0)       # Left state
    SR =  0           # Right state
    LL = (0, 0)       # Left lock
    LR = (0, 0)       # Right lock
    k  = (0, 0)       # Left lock's key

    def __init__(self, group, g, name, debug=False):
        self.group = group
        self.g = g
        self.name = name
        self.sk = self.group.random(ZR)
        self.pk = self.g ** self.sk
        self._debug=debug
        self._setState(_WAIT_SETUP)

    def init_transaction(self, amount, path):
        self._lock = Lock()
        self._lock.acquire()
        self._setState(_SETUP, {"amount": amount, "path": path})
        return self._lock

    def _vf(self, l, k):
        m, pk = l
        R, s = k
        e = self.group.hash((pk, R, m))
        return self.g ** s == R * (pk ** e)
    
    def _log(self, *args):
        if self._debug is True:
            print(*args)

    def _print_state(self):
        self._log(f"STATE:\tY\': {self.SI[0]}")
        self._log(f"\t\t Y: {self.SI[1]}")
        self._log(f"\t\t y: {self.SI[2]}")
        self._log(f"\t\t k: {self.k[1]}")
        self._log()

    def _setState(self, state_class, state_info={}):
        self._state = state_class(state_info)
        self._state.node = self
        self._state.default_action()

    def _msg_receive(self, msg):
        if msg["__expected_state__"] != self._state.__class__.__name__:
            raise Exception(f"({self.name}) Unexpected state {msg['__expected_state__']}: {self._state.__class__.__name__} expected.")
        self._state.msg_receive(msg)

    def _msg_send(self, recipient, msg, expected_state):
        msg["__expected_state__"] = expected_state.__name__
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(recipient)
            sock.sendall(objectToBytes(msg, self.group))

    def _nizk_prove(self, x):
        h = self.g ** x
        r = self.group.random(ZR)
        u = self.g ** r
        c = self.group.hash((self.g, h, u))
        return (h, (u, c, r+c*x))
    
    def _nizk_verify(self, h, proof):
        u, c, z = proof
        if c != self.group.hash((self.g, h, u)): return False
        return self.g**z == u*h**c

    def _commit(self, value):
        r = self.group.random(ZR)
        c = self.group.hash((r, *value))
        return (r, c)
    
    def _commit_verify(self, com, decom, value):
        c = self.group.hash((decom, *value))
        return c == com
    
    def _abort_protocol(self, msg):
        self._log(f"Protocol Error: {msg}")
        exit()
        
class _State(ABC):
    def __init__(self, state_info={}):
        self.state_info = state_info

    @property
    def node(self) -> Node: 
        return self._node

    @node.setter
    def node(self, node: Node) -> None: 
        self._node = node

    def default_action(self) -> None:
        pass

    @abstractmethod
    def msg_receive(self, msg) -> None:
        pass

class _SETUP(_State):
    def default_action(self):
        amount, path = self.state_info["amount"], self.state_info["path"]
        path.insert(0, self.node.address)
        self.node.rightNode = tuple(path[1])
        y = self.node.group.random(ZR)
        Y = self.node.g ** y
        self.node.SI = (0, Y, y)
        self.node._print_state()
        
        kn = y
        Yi = Y
        for i, n in enumerate(path[1:-1], start=1):
            yi = self.node.group.random(ZR)
            kn = kn + yi
            Yi_left = Yi
            Yi = Yi_left * (self.node.g ** yi)

            self.node._msg_send(tuple(n), {
                "Yi_prev": Yi_left,
                "yi": yi,
                "leftNode": path[i-1],
                "rightNode": path[i+1],
                "k": 0,
                "proof": self.node._nizk_prove(kn)
            }, _WAIT_SETUP)

        self.node._msg_send(tuple(path[-1]), {
            "Yi_prev": Yi,
            "yi": 0,
            "leftNode": path[-2],
            "rightNode": ('', 0),
            "k": kn,
            "proof": self.node._nizk_prove(kn)
        }, _WAIT_SETUP)

        self.node._setState(_LOCK_SENDER_1, {"amount": amount})

    def msg_receive(self, msg) -> None:
        raise Exception("Not available.")

class _WAIT_SETUP(_State):
    def default_action(self):
        if self.node._lock is not None:
            self.node._lock.release()

    def msg_receive(self, msg) -> None:
        if 'action' in msg and msg['action'] == "send":
            self.node.init_transaction(msg['amount'], msg['path'])
            return

        if not self.node._nizk_verify(*msg["proof"]):
            self.node._abort_protocol("Invalid proof")

        ki = msg["k"]
        Yprev = msg["Yi_prev"]
        y = msg["yi"]
        Y = Yprev * (self.node.g ** y) if ki == 0 else 0
        
        self.node.SI = (Yprev, Y, y)
        self.node.k = (0, ki)
        self.node._print_state()

        self.node.leftNode = tuple(msg["leftNode"])
        self.node.rightNode = tuple(msg["rightNode"])
        self.node._setState(_LOCK_RECIPIENT_2)

class _LOCK_SENDER_1(_State):
    def default_action(self):
        self.node._setState(_LOCK_SENDER_3)
        self.node._msg_send(self.node.rightNode, {
            "amount": self.state_info["amount"],
            "pk_prev": self.node.pk,
        }, _LOCK_RECIPIENT_2)

    def msg_receive(self, msg) -> None:
        raise Exception("Not available.")

class _LOCK_RECIPIENT_2(_State):
    def msg_receive(self, msg) -> None:
        self.node.pkL = self.node.pk * msg["pk_prev"]
        r = self.node.group.random(ZR)
        R = self.node.g ** r
        proof = self.node._nizk_prove(r)
        decom, com = self.node._commit((R, proof[0], *proof[1]))

        self.node._setState(_LOCK_RECIPIENT_4, {
            "r": r, 
            "R": R, 
            "amount": msg["amount"],
            "proof": proof,
            "decom": decom })
        self.node._msg_send(self.node.leftNode, {
            "pk_next": self.node.pk,
            "com": com
        }, _LOCK_SENDER_3)

class _LOCK_SENDER_3(_State):
    def msg_receive(self, msg):
        self.node.pkR = self.node.pk * msg["pk_next"]
        r = self.node.group.random(ZR)
        R = self.node.g ** r  

        self.node._setState(_LOCK_SENDER_5, {
            'r': r,
            'R': R,
            "com": msg["com"] })
        self.node._msg_send(self.node.rightNode, {
            "Rprev": R,
            "proof": self.node._nizk_prove(r)
        }, _LOCK_RECIPIENT_4)

class _LOCK_RECIPIENT_4(_State):
    def msg_receive(self, msg) -> None:
        if not self.node._nizk_verify(*msg["proof"]):
            self.node._abort_protocol("Invalid proof!")

        R, r = self.state_info["R"], self.state_info["r"]
        Rprev = msg["Rprev"]
        Yprev, _, _ = self.node.SI
        amount = self.state_info["amount"]
        m = f"I'll pay {amount} to {self.node.name}"

        rfactor =  Rprev * R * Yprev
        e = self.node.group.hash((
         self.node.pkL,
            rfactor,
            m
        ))

        s = r + (e * self.node.sk) 

        self.node._setState(_LOCK_RECIPIENT_6, {
            "rfactor": rfactor, 
            "R": R, 
            "Rprev": Rprev,
            "e": e })
        self.node._msg_send(self.node.leftNode, {
            "amount": amount,
            "R": R,
            "s": s,
            "m": m,
            "proof": self.state_info["proof"],
            "decom": self.state_info["decom"]
        }, _LOCK_SENDER_5)
        
class _LOCK_SENDER_5(_State):
    def msg_receive(self, msg) -> None:
        if not self.node._nizk_verify(*msg["proof"]):
            self.node._abort_protocol("Invalid proof!")

        r = self.state_info["r"]
        R = self.state_info["R"]
        Rnext, s = msg["R"], msg["s"]
        proof = msg["proof"]

        if not self.node._commit_verify(self.state_info["com"], msg["decom"], (Rnext, proof[0], *proof[1])):
            self.node._abort_protocol("Invalid commitment!")

        amount, m = msg["amount"], msg["m"]
        _, Y, _ = self.node.SI

        rfactor = R * Rnext * Y
        e = self.node.group.hash((
            self.node.pkR,
            rfactor,
            m
        ))

        if self.node.g ** s != Rnext * (self.node.pkR / (self.node.g ** self.node.sk)) ** e:
            self.node._abort_protocol("Invalid signature!")

        sp = s + r + (e * self.node.sk)
        self.node.LR = (m, self.node.pkR)
        self.node.SR = sp

        self.node._setState(_WAIT_RELEASE)
        self.node._msg_send(self.node.rightNode, {
            "amount": amount,
            "m": m,
            "sp": sp
        }, _LOCK_RECIPIENT_6)

class _LOCK_RECIPIENT_6(_State):
    def msg_receive(self, msg) -> None:
        rfactor, e = self.state_info["rfactor"], self.state_info["e"]
        R, Rprev = self.state_info["R"], self.state_info["Rprev"]
        amount, m, sp = msg["amount"], msg["m"], msg["sp"]

        self.node.LL = (m, self.node.pkL)
        self.node.SL = (rfactor, sp)

        if self.node.g ** sp != Rprev * R * self.node.pkL ** e:
            self.node._abort_protocol("Invalid signature!")

        self.node._log()
        self.node._log(f"Left lock:\t m: {self.node.LL[0]}")
        self.node._log(f"\t\tpk: {self.node.LL[1]}")
        self.node._log(f"\t\t R: {self.node.SL[0]}")
        self.node._log(f"\t\t s: {self.node.SL[1]}")

        if self.node.k[1] == 0:
            self.node._setState(_LOCK_SENDER_1, {"amount": amount-self.node.transaction_fee})
        else:
            self.node._setState(_RELEASE, {"k": self.node.k})

class _WAIT_RELEASE(_State):
    def msg_receive(self, msg) -> None:
        self.node.k = (msg["W0"], msg["w"])
        self.node._log(f"VALID KEY: {self.node._vf(self.node.LR, self.node.k)}")
        if(self.node.leftNode != ('', 0)):
            self.node._setState(_RELEASE, {"k": self.node.k})
        else:
            self.node._setState(_WAIT_SETUP)

class _RELEASE(_State):
    def default_action(self):
        k = self.state_info["k"]
        _, _, y = self.node.SI
        W0, w1 = self.node.SL
        _, s = k
        
        w = w1 + s - (self.node.SR + y)
        self.node._log()
        self.node._log(f"Key:\tW0: {W0}")
        self.node._log(f"\t w: {w}")

        self.node._setState(_WAIT_SETUP)
        self.node._msg_send(self.node.leftNode, {
            "W0": W0,
            "w": w
        }, _WAIT_RELEASE)

    def msg_receive(self, msg) -> None:
        raise Exception("Not available.")