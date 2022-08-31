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
    R = None
    rfactor = None
    e = None
    sp = None
    

    def __init__(self, group, g, name, sk, pkL, pkR):
        self.group = group
        self.g = g
        self.name = name
        self.sk = sk
        self.pkL = pkL
        self.pkR = pkR

        self.setState(_WAIT())
        # Picks a free port and starts a socket
        # self._sock = socket.socket()
        # self._sock.bind(('', 0))

    def __del__(self):
        pass
        # self._sock.close()

    def setState(self, state):
        print(f"CHANGE {self.name}: {self._state.__class__.__name__} to {state.__class__.__name__}")
        self._state = state
        self._state.node = self

    def msg_receive(self, msg):
        #print(f"{self.name}")
        self._state.msg_receive(msg)

    def msg_send(self, recipient, msg):
        print(f"SEND: {self.name} -> {recipient.name}: {msg} ")
        recipient.msg_receive(msg)
    
    def init_transaction(self, amount, path):
        if type(self._state) != _WAIT:
            raise Exception("Node is not currently free.")
        self.setState(_SENDING())        

        # SETUP PHASE
        self.rightNode = path[0]
        self.y = self.group.random(ZR)
        self.Y = self.g ** self.y
        
        self.kn = self.y
        Yi = self.Y
        for i, n in enumerate(path[:-1]):
            yi = self.group.random(ZR)
            self.kn = self.kn * yi
            Yi_prev = Yi
            Yi = Yi_prev * (self.g ** yi)

            self.msg_send(n, {
                "action": "RECEIVE",
                "Yi_prev": Yi_prev,
                "yi": yi,
                "leftNode": path[i-1] if i != 0 else self,
                "rightNode": path[i+1],
                "kn": None
            })

        self.msg_send(path[-1], {
            "action": "RECEIVE",
            "Yi_prev": Yi,
            "yi": 0,
            "leftNode": path[-2],
            "rightNode": None,
            "kn": self.kn
        })

        self.init_lock(amount)

        self.setState(_WAIT())   

    def init_lock(self, amount):
        self.setState(_LOCK_SENDER_1())

        self.r = self.group.random(ZR)
        self.R = self.g ** self.r
        self.setState(_LOCK_SENDER_3())
        self.msg_send(self.rightNode, {
            "action": "LOCK_RECIPIENT_2",
            "amount": amount,
            "Rprev": self.R
        })




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
        if msg["action"] == "RECEIVE":
            self.node.Yprev = msg["Yi_prev"]
            self.node.y = msg["yi"]
            self.node.kn = msg["kn"]
            self.node.leftNode, self.node.rightNode = msg["leftNode"], msg["rightNode"]
            self.node.Y = self.node.Yprev * (self.node.g ** self.node.y)
            print(f"{self.node.name}: {self.node.leftNode} {self.node} {self.node.rightNode}")
            self.node.setState(_LOCK_RECIPIENT_2())
        else:
            print(f"ERROR: {self.node.name} received {msg['action']}")


class _LOCK_SENDER_1(_State):
    def msg_receive(self, msg) -> None:
        raise Exception("Not available.")


class _LOCK_RECIPIENT_2(_State):
    def msg_receive(self, msg) -> None:
        if msg["action"] == "LOCK_RECIPIENT_2":
            Rprev, amount = msg["Rprev"], msg["amount"]

            self.node.r = self.node.group.random(ZR)
            self.node.R = self.node.g ** self.node.r
            self.node.rfactor = self.node.R * Rprev * self.node.Yprev
            self.node.e = self.node.group.hash((
                self.node.pkL,
                self.node.rfactor,
                amount
            ))

            s = self.node.r + (self.node.e * self.node.sk) 

            self.node.setState(_LOCK_RECIPIENT_4())
            self.node.msg_send(self.node.leftNode, {
                "action": "LOCK_SENDER_3",
                "amount": amount,
                "R": self.node.R,
                "s": s
            })
        else:
            print(f"ERROR: {self.node.name} received {msg['action']}")

           

class _LOCK_SENDER_3(_State):
    def msg_receive(self, msg) -> None:
        if msg["action"] == "LOCK_SENDER_3":
            Rnext, s, amount = msg["R"], msg["s"], msg["amount"]

            self.node.e = self.node.group.hash((
                self.node.pkR,
                self.node.R * Rnext * self.node.Y,
                amount
            ))

            self.node.sp = s + self.node.r + (self.node.e * self.node.sk)

            self.node.setState(_WAIT_RELEASE)
            self.node.msg_send(self.node.rightNode, {
                "action": "LOCK_RECIPIENT_4",
                "amount": amount,
                "sp": self.node.sp
            })
        else:
            print(f"ERROR: {self.node.name} received {msg['action']}")


class _LOCK_RECIPIENT_4(_State):
    def msg_receive(self, msg) -> None:
        if msg["action"] == "LOCK_RECIPIENT_4":
            amount, self.node.sp = msg["amount"], msg["sp"]

            if self.node.kn != None:
                self.node.init_lock(amount-self.node.TRANSACTION_FEE)
            else:
                print("END!")
        else:
            print(f"ERROR: {self.node.name} received {msg['action']}")


class _WAIT_RELEASE(_State):
    def msg_receive(self, msg) -> None:
        pass



class _SENDING(_State):
    def msg_receive(self, msg) -> None:
        pass