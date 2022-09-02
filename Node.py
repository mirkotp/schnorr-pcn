from abc import ABC, abstractmethod
from charm.toolbox.ecgroup import ZR

class Node:
    _state = None
    transaction_fee = 1

    leftNode = None
    rightNode = None

    # Protocol variables
    pkL = None              # Shared key with left node
    pkR = None              # Shared key with right node
    SI = (None, None, None) # State
    SL = (None, None)       # Left state
    SR =  None              # Right state
    LL = (None, None)       # Left lock
    LR = (None, None)       # Right lock
    k  = (None, None)       # Left lock's key

    def __init__(self, group, g, name):
        self.group = group
        self.g = g
        self.name = name
        self.sk = self.group.random(ZR)
        self.pk = self.g ** self.sk
  
        self._setState(_WAIT_SETUP)
        # Picks a free port and starts a socket
        # self._sock = socket.socket()
        # self._sock.bind(('', 0))

    def __del__(self):
        pass
        # self._sock.close()

    def init_transaction(self, amount, path):
        self._setState(_SETUP, {"amount": amount, "path": path})

    def vf(self, l, k):
        m, pk = l
        R, s = k
        e = self.group.hash((pk, R, m))        
        return self.g ** s == R * (pk ** e)
    
    def _log(self, msg):
        print(f"{self.name}: {msg}")

    def _setState(self, state_class, state_info={}):
        self._log(f"STATE_CHANGE: {self._state.__class__.__name__} to {state_class.__name__}")
        self._state = state_class(state_info)
        self._state.node = self
        self._state.default_action()

    def _msg_receive(self, msg):
        if msg["__expected_state__"] != self._state.__class__.__name__:
            raise Exception(f"({self.name}) Unexpected state {msg['__expected_state__']}: {self._state.__class__.__name__} expected.")
        self._state.msg_receive(msg)

    def _msg_send(self, recipient, msg, expected_state):
        msg["__expected_state__"] = expected_state.__name__
        recipient._msg_receive(msg)

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
        self.node.rightNode = path[0]
        y = self.node.group.random(ZR)
        Y = self.node.g ** y

        self.node.SI = (None, Y, y)
        
        kn = y
        Yi = Y
        for i, n in enumerate(path[:-1]):
            yi = self.node.group.random(ZR)
            kn = kn + yi
            Yi_left = Yi
            Yi = Yi_left * (self.node.g ** yi)

            self.node._msg_send(n, {
                "action": "RECEIVE",
                "Yi_prev": Yi_left,
                "yi": yi,
                "leftNode": path[i-1] if i != 0 else self.node,
                "rightNode": path[i+1],
                "k": None
            }, _WAIT_SETUP)

        self.node._msg_send(path[-1], {
            "action": "RECEIVE",
            "Yi_prev": Yi,
            "yi": 0,
            "leftNode": path[-2],
            "rightNode": None,
            "k": kn
        }, _WAIT_SETUP)

        self.node._setState(_LOCK_SENDER_1, {"amount": amount})

    def msg_receive(self, msg) -> None:
        raise Exception("Not available.")

class _WAIT_SETUP(_State):
    def msg_receive(self, msg) -> None:
        Yprev = msg["Yi_prev"]
        y = msg["yi"]
        Y = Yprev * (self.node.g ** y)

        self.node.SI = (Yprev, Y, y)
        self.node.k = (None, msg["k"])
        self.node.leftNode, self.node.rightNode = msg["leftNode"], msg["rightNode"]
        self.node._setState(_LOCK_RECIPIENT_2)

class _LOCK_SENDER_1(_State):
    def default_action(self):
        amount = self.state_info["amount"]
        r = self.node.group.random(ZR)
        R = self.node.g ** r  

        self.node._setState(_LOCK_SENDER_3, {'r': r, 'R': R})
        self.node._msg_send(self.node.rightNode, {
            "action": "LOCK_RECIPIENT_2",
            "amount": amount,
            "Rprev": R,
            "pk_prev": self.node.pk
        }, _LOCK_RECIPIENT_2)

    def msg_receive(self, msg) -> None:
        raise Exception("Not available.")

class _LOCK_RECIPIENT_2(_State):
    def msg_receive(self, msg) -> None:
        Rprev, amount, pk_prev = msg["Rprev"], msg["amount"], msg["pk_prev"]
        Yprev, _, _ = self.node.SI
        self.node.pkL = self.node.pk * pk_prev

        r = self.node.group.random(ZR)
        R = self.node.g ** r
        rfactor =  Rprev * R * Yprev
        e = self.node.group.hash((
         self.node.pkL,
            rfactor,
            amount
        ))

        s = r + (e * self.node.sk) 

        self.node._setState(_LOCK_RECIPIENT_4, {"rfactor": rfactor})
        self.node._msg_send(self.node.leftNode, {
            "action": "LOCK_SENDER_3",
            "amount": amount,
            "R": R,
            "s": s,
            "pk_next": self.node.pk
        }, _LOCK_SENDER_3)
        
class _LOCK_SENDER_3(_State):
    def msg_receive(self, msg) -> None:
        r = self.state_info["r"]
        R = self.state_info["R"]
        Rnext, s, amount, pk_next = msg["R"], msg["s"], msg["amount"], msg["pk_next"]
        _, Y, _ = self.node.SI
        self.node.pkR = self.node.pk * pk_next

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

        self.node._setState(_WAIT_RELEASE)
        self.node._msg_send(self.node.rightNode, {
            "action": "LOCK_RECIPIENT_4",
            "amount": amount,
            "sp": sp
        }, _LOCK_RECIPIENT_4)

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
            self.node._setState(_LOCK_SENDER_1, {"amount": amount-self.node.transaction_fee})
        else:
            self.node._setState(_RELEASE, {"k": self.node.k})

class _WAIT_RELEASE(_State):
    def msg_receive(self, msg) -> None:
        self.node.k = (msg["W0"], msg["w"])
        self.node._log(f"VALID LOCK: {self.node.vf(self.node.LR, self.node.k)}")
        if(self.node.leftNode is not None):
            self.node._setState(_RELEASE, {"k": self.node.k})

class _RELEASE(_State):
    def default_action(self):
        k = self.state_info["k"]
        _, _, y = self.node.SI
        W0, w1 = self.node.SL
        _, s = k
        SR = self.node.SR if self.node.SR is not None else 0

        w = w1 + s - (SR + y)
        self.node._setState(_WAIT_SETUP)
        self.node._msg_send(self.node.leftNode, {
            "W0": W0,
            "w": w
        }, _WAIT_RELEASE)

    def msg_receive(self, msg) -> None:
        raise Exception("Not available.")