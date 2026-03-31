__all__ = ["RequestHandler"]

from typing import Optional, Union
from abc import ABC, abstractmethod

from include.classes.handler import ConnectionHandler


class RequestHandler(ABC):
    """
    Abstract base class for handling requests.
    Attributes:
        data_schema (dict): A dictionary defining the expected schema for request data.
    Methods:
        handle():
            Abstract method to process a request. Must be implemented by subclasses.
            Returns:
                1. -> None
                    该结果将被忽略。
                2. -> int
                    只有 result
                3. -> tuple[int, str]
                    这种情况下 int 为 result, 第二个元素必定为 target。
                4. -> tuple[int, str, dict]
                    这种情况下 int 为 result, 第二个元素必定为 target, 第三个元素为 data。
                5. -> tuple[int, str, str]
                    这种情况下 int 为 result, 第二个元素必定为 target, 第三个元素为 username。
                6. -> tuple[int, str, dict, str]
                    这种情况下 int 为 result, 第二个元素必定为 target, 第三个元素为 data, 第四个元素为 username。
    """

    # This property defines the json structure of the request data.
    data_schema: dict = {}
    # Defines whether the handler needs auth check before handling a request.
    require_auth: bool = False

    @abstractmethod
    def handle(self, handler: ConnectionHandler) -> Union[
        int,
        tuple[int, Optional[str]],
        tuple[int, Optional[str], dict],
        tuple[int, Optional[str], str],
        tuple[int, Optional[str], dict, str],
        None,
    ]:
        pass
