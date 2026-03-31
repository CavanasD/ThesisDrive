"""
Search handlers for documents and directories.

Provides functionality to search for documents and directories by name,
with permission filtering, result limiting, and sorting capabilities.
"""

__all__ = ["RequestSearchHandler"]

import time
from typing import List, Dict, Any

from include.classes.handler import ConnectionHandler
from include.classes.enum.permissions import Permissions
from include.classes.request import RequestHandler
from include.conf_loader import global_config
from include.database.handler import Session
from include.database.models.classic import User
from include.database.models.entity import NoActiveRevisionsError
from include.util.recursive.ancestors import (
    search_documents_with_access,
    search_folders_with_access,
)
from include.util.recursive.check import check_access_for_object
from include.util.fetch.fetch import prefetch_user_blocks, batch_prefetch_granted_ids


class RequestSearchHandler(RequestHandler):
    """
    Handles the "search" action for finding documents and directories by name.

    Features:
    1. Accepts a search query (name) as the main parameter
    2. Returns matching objects with their ID and parent directory ID
    3. Filters results based on user read permissions
    4. Supports limiting the maximum number of search results
    5. Supports sorting by multiple criteria (time, size, name, etc.)
    """

    data_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            "sort_by": {
                "type": "string",
                "enum": ["name", "created_time", "size", "last_modified"],
            },
            "sort_order": {"type": "string", "enum": ["asc", "desc"]},
            "search_documents": {"type": "boolean"},
            "search_directories": {"type": "boolean"},
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        """
        Handle the search request.

        Args:
            handler: The connection handler containing request data

        Returns:
            Tuple containing status code, query, and username for audit logging
        """
        query: str = handler.data["query"]
        limit: int = handler.data.get("limit", 100)
        sort_by: str = handler.data.get("sort_by", "name")
        sort_order: str = handler.data.get("sort_order", "asc")
        search_documents: bool = handler.data.get("search_documents", True)
        search_directories: bool = handler.data.get("search_directories", True)

        with Session() as session:
            user = session.get(User, handler.username)
            assert user is not None

            now = time.time()

            results: Dict[str, List[Dict[str, Any]]] = {
                "documents": [],
                "directories": [],
            }

            # Preload block entries
            is_globally_blocked, blocked_ids = prefetch_user_blocks(
                session, user, "read", now
            )

            # Search documents
            if search_documents and (
                not is_globally_blocked
                or Permissions.SUPER_LIST_DIRECTORY in user.all_permissions
            ):
                documents, doc_ancestors, doc_oaes = search_documents_with_access(
                    session, query, now
                )

                doc_ids = [doc.id for doc in documents]
                explicitly_granted_doc_ids = batch_prefetch_granted_ids(
                    session, user, doc_ids, "document", "read", now
                )

                for document in documents:
                    if not document.active:
                        continue
                    if (
                        document.id in blocked_ids
                        and Permissions.SUPER_LIST_DIRECTORY not in user.all_permissions
                    ):  # This is because people who have `super_list_directory` can still see blocked documents via `list_directory`.
                        continue
                    if document.id in explicitly_granted_doc_ids:
                        pass
                    else:
                        if not check_access_for_object(
                            document,
                            user,
                            "read",
                            doc_ancestors,
                            doc_oaes,
                            recursive=global_config["access"][
                                "enable_access_recursive_check"
                            ],
                        ):
                            continue

                    try:
                        latest_revision = document.get_latest_revision()
                        size = latest_revision.file.size if latest_revision.file else 0
                        last_modified = latest_revision.created_time
                    except (NoActiveRevisionsError, AttributeError):
                        size = 0
                        last_modified = document.created_time

                    results["documents"].append(
                        {
                            "id": document.id,
                            "name": document.title,
                            "parent_id": document.folder_id,
                            "created_time": document.created_time,
                            "last_modified": last_modified,
                            "size": size,
                            "type": "document",
                        }
                    )

            # Search directories
            if search_directories and (
                not is_globally_blocked
                or Permissions.SUPER_LIST_DIRECTORY in user.all_permissions
            ):
                directories, dir_ancestors, dir_oaes = search_folders_with_access(
                    session, query, now
                )

                dir_ids = [d.id for d in directories]
                explicitly_granted_dir_ids = batch_prefetch_granted_ids(
                    session, user, dir_ids, "directory", "read", now
                )

                for directory in directories:
                    if (
                        directory.id in blocked_ids
                        and Permissions.SUPER_LIST_DIRECTORY not in user.all_permissions
                    ):
                        continue

                    if directory.id in explicitly_granted_dir_ids:
                        pass
                    else:
                        if not check_access_for_object(
                            directory,
                            user,
                            "read",
                            dir_ancestors,
                            dir_oaes,
                            recursive=global_config["access"][
                                "enable_access_recursive_check"
                            ],
                        ):
                            continue

                    results["directories"].append(
                        {
                            "id": directory.id,
                            "name": directory.name,
                            "parent_id": directory.parent_id,
                            "created_time": directory.created_time,
                            "type": "directory",
                        }
                    )

            # Sort results
            all_results = results["documents"] + results["directories"]

            # Sort by the specified field
            if sort_by == "name":
                all_results.sort(
                    key=lambda x: x["name"].lower(), reverse=(sort_order == "desc")
                )
            elif sort_by == "created_time":
                all_results.sort(
                    key=lambda x: x["created_time"], reverse=(sort_order == "desc")
                )
            elif sort_by == "size":
                all_results.sort(
                    key=lambda x: x.get("size", 0), reverse=(sort_order == "desc")
                )
            elif sort_by == "last_modified":
                all_results.sort(
                    key=lambda x: x.get("last_modified", x["created_time"]),
                    reverse=(sort_order == "desc"),
                )

            # Apply limit
            all_results = all_results[:limit]

            # Separate back into documents and directories
            final_documents = [r for r in all_results if r["type"] == "document"]
            final_directories = [r for r in all_results if r["type"] == "directory"]

            response_data = {
                "documents": final_documents,
                "directories": final_directories,
                "total_count": len(all_results),
                "query": query,
            }

            handler.conclude_request(
                200,
                response_data,
                f"Search completed successfully. Found {len(all_results)} result(s).",
            )
            return 0, query, handler.username
