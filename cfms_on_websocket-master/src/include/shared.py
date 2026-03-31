__all__ = ["clients", "clients_lock", "lockdown_enabled"]

import threading
from include.classes.frame import MultiplexConnection


clients: set[MultiplexConnection] = set()
clients_lock = threading.Lock()
lockdown_enabled = threading.Event()
