__all__ = [
    "MissingComponentsError",
    "InvaildPasswordLengthError",
    "check_passwd_requirements",
]

from typing import List
from typing import Optional


class MissingComponentsError(ValueError):
    def __init__(self, missing: set[str]) -> None:
        self.missing = missing

    def __str__(self) -> str:
        return (
            f"Password is missing the necessary characters: {", ".join(self.missing)}"
        )


class InvaildPasswordLengthError(ValueError):
    def __init__(
        self,
        length: int,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
    ) -> None:
        self.length = length
        self.min_length = min_length
        self.max_length = max_length
        assert (self.min_length and self.max_length) or (
            not self.min_length and not self.max_length
        )

    def __str__(self) -> str:

        if self.min_length and self.max_length:
            return f"Password does not meet the length requirement ({self.min_length} ~ {self.max_length})"
        else:
            return f"Password does not meet the length requirement"


def check_passwd_requirements(
    passwd: str,
    min_length: int,
    max_length: int,
    must_contain: Optional[List[List[str]]] = None,
) -> None:
    length = len(passwd)
    if not (min_length <= length <= max_length):
        raise InvaildPasswordLengthError(length, min_length, max_length)

    pwd_set = set(passwd)

    if must_contain is None:
        must_contain = []

    for group in must_contain:
        each_set = set(group)
        if not pwd_set & each_set:
            raise MissingComponentsError(each_set)
