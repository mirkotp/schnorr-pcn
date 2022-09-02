from abc import ABC, abstractmethod
from charm.toolbox.ecgroup import ZR

class Node:
    _state = None
    TRANSACTION_FEE = 1

    leftNode = None
    rightNode = None

    SI = (None, None, None) # State
    SL = (None, None)       # Left state
    SR =  None              # Right state
    LL = (None, None)       # Left lock
    LR = (None, None)       # Right lock
    k  = (None, None)       # Key for the left lock

    def __init__(self, group, g, name, sk, pkL, pkR):
        self.group = group
        self.g = g
        self.name = name
        self.sk = sk
        self.pkL = pkL
        self.pkR = pkR

        self.setState(_WAIT_SETUP)
        # Picks a free port and starts a socket
        # self._sock = socket.socket()
        # self._sock.bind(('', 0))

    def __del__(self):
        pass
        # self._sock.close()

    def vf(self, l, k):
        m, pk = l
        R, s = k
        e = self.group.hash((pk, R, m))        
        return self.g ** s == R * (pk ** e)
    
    def log(self, msg):
        print(f"{self.name}: {msg}")

    def setState(self, state_class, state_info={}):
        self.log(f"STATE_CHANGE: {self._state.__class__.__name__} to {state_class.__name__}")
        self._state = state_class(state_info)
        self._state.node = self

    def _msg_receive(self, msg):
        if msg["__expected_state__"] != self._state.__class__.__name__:
            raise Exception(f"({self.name}) Unexpected state {msg['__expected_state__']}: {self._state.__class__.__name__} expected.", )
        self._state.msg_receive(msg)

    def _msg_send(self, recipient, msg, new_state, recipient_state, next_state_info={}):
        msg["__expected_state__"] = recipient_state.__name__
        self.setState(new_state, next_state_info)
        recipient._msg_receive(msg)
    
    def setup_transaction(self, amount, path):
        if type(self._state) != _WAIT_SETUP:
            raise Exception("Node is not currently free.")
        self.setState(_SETUP)        

        # SETUP PHASE
        self.rightNode = path[0]
        y = self.group.random(ZR)
        Y = self.g ** y

        self.SI = (None, Y, y)
        
        kn = y
        Yi = Y
        for i, n in enumerate(path[:-1]):
            yi = self.group.random(ZR)
            kn = kn + yi
            Yi_left = Yi
            Yi = Yi_left * (self.g ** yi)

            self._msg_send(n, {
                "action": "RECEIVE",
                "Yi_prev": Yi_left,
                "yi": yi,
                "leftNode": path[i-1] if i != 0 else self,
                "rightNode": path[i+1],
                "k": None
            }, _SETUP, _WAIT_SETUP)

        self._msg_send(path[-1], {
            "action": "RECEIVE",
            "Yi_prev": Yi,
            "yi": 0,
            "leftNode": path[-2],
            "rightNode": None,
            "k": kn
        }, _LOCK_SENDER_1, _WAIT_SETUP)

        self.lock(amount)
        self.log("END!")

    def lock(self, amount):
        r = self.group.random(ZR)
        R = self.g ** r
        self._msg_send(self.rightNode, {
            "action": "LOCK_RECIPIENT_2",
            "amount": amount,
            "Rprev": R
        }, _LOCK_SENDER_3, _LOCK_RECIPIENT_2, next_state_info={'r': r, 'R': R})

    def release(self, k):
        _, _, y = self.SI
        W0, w1 = self.SL
        _, s = k
        SR = self.SR if self.SR is not None else 0

        w = w1 + s - (SR + y)
        self._msg_send(self.leftNode, {
            "W0": W0,
            "w": w
        }, _WAIT_SETUP, _WAIT_RELEASE)

class _State(ABC):
    def __init__(self, state_info={}):
        self.state_info = state_info

    @property
    def node(self) -> Node: 
        return self._node

    @node.setter
    def node(self, node: Node) -> None: 
        self._node = node

    @abstractmethod
    def msg_receive(self, msg) -> None:
        pass
class _WAIT_SETUP(_State):
    def msg_receive(self, msg) -> None:
        Yprev = msg["Yi_prev"]
        y = msg["yi"]
        Y = Yprev * (self.node.g ** y)

        self.node.SI = (Yprev, Y, y)
        self.node.k = (None, msg["k"])
        self.node.leftNode, self.node.rightNode = msg["leftNode"], msg["rightNode"]
        self.node.setState(_LOCK_RECIPIENT_2)

class _LOCK_SENDER_1(_State):
    def msg_receive(self, msg) -> None:
        raise Exception("Not available.")

class _LOCK_RECIPIENT_2(_State):
    def msg_receive(self, msg) -> None:
        Rprev, amount = msg["Rprev"], msg["amount"]
        Yprev, _, _ = self.node.SI

        r = self.node.group.random(ZR)
        R = self.node.g ** r
        rfactor =  Rprev * R * Yprev
        e = self.node.group.hash((
         self.node.pkL,
            rfactor,
            amount
        ))

        s = r + (e * self.node.sk) 

        self.node._msg_send(self.node.leftNode, {
            "action": "LOCK_SENDER_3",
            "amount": amount,
            "R": R,
            "s": s,
            "qq": self.node.sk
        }, _LOCK_RECIPIENT_4, _LOCK_SENDER_3, next_state_info={"rfactor": rfactor})
        
class _LOCK_SENDER_3(_State):
    def msg_receive(self, msg) -> None:
        r = self.state_info["r"]
        R = self.state_info["R"]
        Rnext, s, amount = msg["R"], msg["s"], msg["amount"]
        _, Y, _ = self.node.SI

        rfactor = R * Rnext * Y
        e = self.node.group.hash((
            self.node.pkR,
            rfactor,
            amount
        ))

        # Verify:
        # self.node.g ** s
        # ==
        # Rnext * (self.node.pkR / (self.node.g ** self.node.sk)) ** self.node.e)

        sp = s + r + (e * self.node.sk)
        self.node.LR = (amount, self.node.pkR)
        self.node.SR = sp

        self.node._msg_send(self.node.rightNode, {
            "action": "LOCK_RECIPIENT_4",
            "amount": amount,
            "sp": sp
        }, _WAIT_RELEASE, _LOCK_RECIPIENT_4)

class _LOCK_RECIPIENT_4(_State):
    def msg_receive(self, msg) -> None:
        rfactor = self.state_info["rfactor"]
        amount, sp = msg["amount"], msg["sp"]

        # Verify:
        # self.node.g ** self.node.spL
        # == 
        # self.node.Rprev * self.node.R * (self.node.pkL ** self.node.e)

        self.node.LL = (amount, self.node.pkR)
        self.node.SL = (rfactor, sp)

        if self.node.k[1] is None:
            self.node.lock(amount-self.node.TRANSACTION_FEE)
        else:
            self.node.release(self.node.k)

class _WAIT_RELEASE(_State):
    def msg_receive(self, msg) -> None:
        self.node.k = (msg["W0"], msg["w"])
        self.node.log(f"VALID LOCK: {self.node.vf(self.node.LR, self.node.k)}")
        if(self.node.leftNode is not None):
            self.node.release(self.node.k)

class _SETUP(_State):
    def msg_receive(self, msg) -> None:
        raise Exception("Not available.")