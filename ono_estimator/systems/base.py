from ..core.data import MTFData
from ..core.models import SignalStatus

class BaseSystem:
    def __init__(self, name: str):
        self.name = name

    def evaluate(self, mtf_data: MTFData) -> SignalStatus:
        raise NotImplementedError
