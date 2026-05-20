from abc import ABC, abstractmethod

from stocks_tool.domain.enums import BrokerName
from stocks_tool.domain.models import BrokerConfigurationStatus, BrokerProfile


class BrokerAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> BrokerName:
        raise NotImplementedError

    @abstractmethod
    def get_profile(self) -> BrokerProfile:
        raise NotImplementedError

    @abstractmethod
    def get_configuration_status(self) -> BrokerConfigurationStatus:
        raise NotImplementedError

