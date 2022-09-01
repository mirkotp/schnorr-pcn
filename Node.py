from abc import ABC, abstractmethod
from charm.toolbox.ecgroup import ZR

class Node:
    _state = None
    TRANSACTION_FEE = 1

    leftNode = None
    rightNode = None
    Yprev = None
    Y = None
    y = None
    kn = None
    r = None
    Rprev = None
    R = None
    rfactorL = None
    rfactorR = None
    eL = None
    eR = None
    sp = None
    spL = None
    
    def __init__(self, group, g, name, sk, pkL, pkR):
        self.group = group
        self.g = g
        self.name = name
        self.sk = sk
        self.pkL = pkL
        self.pkR = pkR

        self.setState(_WAIT)
        # Picks a free port and starts a socket
        # self._sock = socket.socket()
        # self._sock.bind(('', 0))

    def __del__(self):
        pass
        # self._sock.close()

    def vf(self, w):
        return self.g ** w == self.rfactorR * (self.pkR ** self.eR)
    
    def log(self, msg):
        print(f"{self.name}: {msg}")

    def setState(self, state_class):
        self.log(f"STATE_CHANGE: {self._state.__class__.__name__} to {state_class.__name__}")
        self._state = state_class()
        self._state.node = self

    def msg_receive(self, msg):
        if msg["__expected_state__"] != self._state.__class__.__name__:
            raise Exception(f"({self.name}) Unexpected state {msg['__expected_state__']}: {self._state.__class__.__name__} expected.", )
        self._state.msg_receive(msg)

    def msg_send(self, recipient, msg, new_state, recipient_state):
        msg["__expected_state__"] = recipient_state.__name__
        self.setState(new_state)
        recipient.msg_receive(msg)
    
    def init_transaction(self, amount, path):
        if type(self._state) != _WAIT:
            raise Exception("Node is not currently free.")
        self.setState(_SETTING_UP)        

        # SETUP PHASE
        self.rightNode = path[0]
        self.y = self.group.random(ZR)
        self.Y = self.g ** self.y
        
        self.kn = self.y
        Yi = self.Y
        for i, n in enumerate(path[:-1]):
            yi = self.group.random(ZR)
            self.kn = self.kn + yi
            Yi_prev = Yi
            Yi = Yi_prev * (self.g ** yi)

            self.msg_send(n, {
                "action": "RECEIVE",
                "Yi_prev": Yi_prev,
                "yi": yi,
                "leftNode": path[i-1] if i != 0 else self,
                "rightNode": path[i+1],
                "kn": 0
            }, _SETTING_UP, _WAIT)

        self.msg_send(path[-1], {
            "action": "RECEIVE",
            "Yi_prev": Yi,
            "yi": 0,
            "leftNode": path[-2],
            "rightNode": None,
            "kn": self.kn
        }, _LOCK_SENDER_1, _WAIT)

        self.lock(amount)
        
        self.log("END!")

    def lock(self, amount):
        self.r = self.group.random(ZR)
        self.R = self.g ** self.r
        self.msg_send(self.rightNode, {
            "action": "LOCK_RECIPIENT_2",
            "amount": amount,
            "Rprev": self.R
        }, _LOCK_SENDER_3, _LOCK_RECIPIENT_2)

    def release(self, k):
        sp = (self.sp if self.sp is not None else 0)
        w = self.spL + k - (sp + self.y)
        self.msg_send(self.leftNode, {
            "w": w
        }, _WAIT, _WAIT_RELEASE)

class _State(ABC):
    @property
    def node(self) -> Node: 
        return self._node

    @node.setter
    def node(self, node: Node) -> None: 
        self._node = node

    @abstractmethod
    def msg_receive(self, msg) -> None:
        pass
class _WAIT(_State):
    def msg_receive(self, msg) -> None:
        self.node.Yprev = msg["Yi_prev"]
        self.node.y = msg["yi"]
        self.node.kn = msg["kn"]
        self.node.leftNode, self.node.rightNode = msg["leftNode"], msg["rightNode"]
        self.node.Y = self.node.Yprev * (self.node.g ** self.node.y)
        
        self.node.setState(_LOCK_RECIPIENT_2)

class _LOCK_SENDER_1(_State):
    def msg_receive(self, msg) -> None:
        raise Exception("Not available.")

class _LOCK_RECIPIENT_2(_State):
    def msg_receive(self, msg) -> None:
        self.node.Rprev, amount = msg["Rprev"], msg["amount"]

        self.node.r = self.node.group.random(ZR)
        self.node.R = self.node.g ** self.node.r
        self.node.rfactorL =  self.node.Rprev * self.node.R * self.node.Yprev
        self.node.eL = self.node.group.hash((
            self.node.pkL,
            self.node.rfactorL,
            amount
        ))

        s = self.node.r + (self.node.eL * self.node.sk) 

        self.node.msg_send(self.node.leftNode, {
            "action": "LOCK_SENDER_3",
            "amount": amount,
            "R": self.node.R,
            "s": s,
            "qq": self.node.sk
        }, _LOCK_RECIPIENT_4, _LOCK_SENDER_3)
        
class _LOCK_SENDER_3(_State):
    def msg_receive(self, msg) -> None:
        Rnext, s, amount = msg["R"], msg["s"], msg["amount"]
        self.node.rfactorR = self.node.R * Rnext * self.node.Y
        self.node.eR = self.node.group.hash((
            self.node.pkR,
            self.node.rfactorR,
            amount
        ))

        # Verify:
        # self.node.g ** s
        # ==
        # Rnext * (self.node.pkR / (self.node.g ** self.node.sk)) ** self.node.e)

        self.node.sp = s + self.node.r + (self.node.eR * self.node.sk)

        self.node.msg_send(self.node.rightNode, {
            "action": "LOCK_RECIPIENT_4",
            "amount": amount,
            "sp": self.node.sp
        }, _WAIT_RELEASE, _LOCK_RECIPIENT_4)

class _LOCK_RECIPIENT_4(_State):
    def msg_receive(self, msg) -> None:
        amount, self.node.spL = msg["amount"], msg["sp"]

        # Verify:
        # self.node.g ** self.node.spL
        # == 
        # self.node.Rprev * self.node.R * (self.node.pkL ** self.node.e)

        if self.node.kn == 0:
            self.node.lock(amount-self.node.TRANSACTION_FEE)
        else:
            self.node.release(self.node.kn)

class _WAIT_RELEASE(_State):
    def msg_receive(self, msg) -> None:
        #self.node.log(f"W0: {msg['W0']}")
        w = msg["w"]
        self.node.log(f"w: {self.node.vf(w)}")
        if(self.node.leftNode is not None):
            self.node.release(w)

class _SETTING_UP(_State):
    def msg_receive(self, msg) -> None:
        raise Exception("Not available.")