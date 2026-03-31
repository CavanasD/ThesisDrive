__all__ = ["validate_access_rules"]

from typing import Any
import jsonschema


schema = {
    "type": "array",  # 'rules' is an array.
    "items": {  # each item in the array is considered as a dict.
        "type": "object",
        "properties": {  # in each dict, key "match" and "match_groups" are expected.
            "match": {
                "type": "string"
            },  # the value of "match" should be a string, indicating the matching mode.
            "match_groups": {
                "type": "array",  # a match group contains a variety of rules.
                "items": {
                    "type": "object",
                    "properties": {
                        "rights": {
                            "type": "object",
                            "properties": {
                                "match": {"type": "string"},
                                "require": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                        "groups": {
                            "type": "object",
                            "properties": {
                                "match": {"type": "string"},
                                "require": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        },
        "required": ["match", "match_groups"],
    },
}


def validate_access_rules(rules: list[dict[str, Any]]) -> None:
    jsonschema.validate(rules, schema)
