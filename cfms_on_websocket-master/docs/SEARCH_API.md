# Search API Documentation

## Overview

The Search API provides functionality to search for documents and directories by name within the CFMS system. The search respects user permissions and provides flexible filtering and sorting options.

## Endpoint

**Action:** `search`

**Authentication:** Required

## Request Format

```json
{
    "action": "search",
    "username": "<username>",
    "token": "<auth_token>",
    "data": {
        "query": "<search_query>",
        "limit": 100,
        "sort_by": "name",
        "sort_order": "asc",
        "search_documents": true,
        "search_directories": true
    }
}
```

### Request Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | - | The search query string. Case-insensitive partial matching. Min length: 1 character. |
| `limit` | integer | No | 100 | Maximum number of results to return. Range: 1-1000. |
| `sort_by` | string | No | "name" | Field to sort results by. Options: `name`, `created_time`, `size`, `last_modified`. |
| `sort_order` | string | No | "asc" | Sort order. Options: `asc` (ascending), `desc` (descending). |
| `search_documents` | boolean | No | true | Whether to include documents in search results. |
| `search_directories` | boolean | No | true | Whether to include directories in search results. |

## Response Format

### Success Response (Code 200)

```json
{
    "code": 200,
    "message": "Search completed successfully. Found 3 result(s).",
    "data": {
        "documents": [
            {
                "id": "doc_id_1",
                "name": "Document Title",
                "parent_id": "folder_id_or_null",
                "created_time": 1234567890.123,
                "last_modified": 1234567891.456,
                "size": 1024,
                "type": "document"
            }
        ],
        "directories": [
            {
                "id": "dir_id_1",
                "name": "Directory Name",
                "parent_id": "parent_folder_id_or_null",
                "created_time": 1234567890.123,
                "type": "directory"
            }
        ],
        "total_count": 3,
        "query": "search term"
    }
}
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `documents` | array | List of matching documents that the user has read permission for. |
| `directories` | array | List of matching directories that the user has read permission for. |
| `total_count` | integer | Total number of results returned (documents + directories). |
| `query` | string | The search query that was executed. |

#### Document Object Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier for the document. |
| `name` | string | Document title/name. |
| `parent_id` | string or null | ID of the parent directory. `null` if at root level. |
| `created_time` | float | Unix timestamp when the document was created. |
| `last_modified` | float | Unix timestamp when the document was last modified. |
| `size` | integer | Size of the document in bytes. |
| `type` | string | Always "document". |

#### Directory Object Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier for the directory. |
| `name` | string | Directory name. |
| `parent_id` | string or null | ID of the parent directory. `null` if at root level. |
| `created_time` | float | Unix timestamp when the directory was created. |
| `type` | string | Always "directory". |

### Error Responses

| Code | Message | Description |
|------|---------|-------------|
| 400 | Validation error | Invalid request parameters (e.g., empty query, invalid sort_by value). |
| 401 | Authentication required | No valid authentication credentials provided. |
| 403 | Invalid user or token | Authentication credentials are invalid or expired. |

## Features

### 1. Permission Filtering

The search automatically filters results based on the authenticated user's read permissions. Users will only see documents and directories they have permission to access.

- Documents without active revisions are excluded from results
- Only items with read permission are returned
- No indication is given that filtered results exist (security by obscurity)

### 2. Case-Insensitive Partial Matching

The search performs case-insensitive partial matching on document titles and directory names:

- Query "test" matches "Test Document", "testing", "Contest", etc.
- Query "doc" matches "Document", "my_docs", "documentation", etc.

### 3. Result Limiting

Control the maximum number of results:

```json
{
    "query": "project",
    "limit": 10
}
```

This limits the total results (documents + directories combined) to 10 items.

### 4. Multi-Criteria Sorting

Results can be sorted by various fields:

**Sort by Name:**
```json
{
    "query": "project",
    "sort_by": "name",
    "sort_order": "asc"
}
```

**Sort by Creation Time:**
```json
{
    "query": "project",
    "sort_by": "created_time",
    "sort_order": "desc"
}
```

**Sort by Size (documents only):**
```json
{
    "query": "project",
    "sort_by": "size",
    "sort_order": "desc"
}
```
Note: Directories have a size of 0 when sorting by size.

**Sort by Last Modified:**
```json
{
    "query": "project",
    "sort_by": "last_modified",
    "sort_order": "desc"
}
```
Note: For directories, `last_modified` equals `created_time`.

### 5. Selective Search

Search only documents or only directories:

**Documents Only:**
```json
{
    "query": "report",
    "search_documents": true,
    "search_directories": false
}
```

**Directories Only:**
```json
{
    "query": "folder",
    "search_documents": false,
    "search_directories": true
}
```

## Usage Examples

### Example 1: Basic Search

**Request:**
```json
{
    "action": "search",
    "username": "user",
    "token": "auth_token_here",
    "data": {
        "query": "meeting"
    }
}
```

**Response:**
```json
{
    "code": 200,
    "message": "Search completed successfully. Found 5 result(s).",
    "data": {
        "documents": [
            {
                "id": "abc123",
                "name": "Meeting Notes - Jan 2024",
                "parent_id": "folder_xyz",
                "created_time": 1704067200.0,
                "last_modified": 1704153600.0,
                "size": 2048,
                "type": "document"
            },
            {
                "id": "def456",
                "name": "Team Meeting Agenda",
                "parent_id": null,
                "created_time": 1703980800.0,
                "last_modified": 1704067200.0,
                "size": 1024,
                "type": "document"
            }
        ],
        "directories": [
            {
                "id": "folder_meeting",
                "name": "Meeting Documents",
                "parent_id": null,
                "created_time": 1703894400.0,
                "type": "directory"
            }
        ],
        "total_count": 3,
        "query": "meeting"
    }
}
```

### Example 2: Search with Sorting and Limit

**Request:**
```json
{
    "action": "search",
    "username": "user",
    "token": "auth_token_here",
    "data": {
        "query": "project",
        "limit": 5,
        "sort_by": "last_modified",
        "sort_order": "desc"
    }
}
```

This returns the 5 most recently modified items matching "project", sorted by modification time in descending order.

### Example 3: Documents-Only Search

**Request:**
```json
{
    "action": "search",
    "username": "user",
    "token": "auth_token_here",
    "data": {
        "query": "report",
        "search_documents": true,
        "search_directories": false,
        "sort_by": "size",
        "sort_order": "desc"
    }
}
```

This returns only documents containing "report", sorted by size with largest files first.

## Performance Considerations

1. **Database Queries**: The search uses database LIKE queries which may be slower for large datasets.
2. **Permission Checks**: Each result is checked for user permissions, which adds overhead.
3. **Sorting**: Results are sorted in memory after permission filtering.
4. **Limit Parameter**: Use the `limit` parameter to reduce load when only a few results are needed.

## Security Considerations

1. **Permission-Based Filtering**: Users only see items they have read permission for.
2. **No Information Disclosure**: The API does not reveal the existence of items the user cannot access.
3. **Authentication Required**: All search requests require valid authentication.
4. **Input Validation**: Search queries and parameters are validated to prevent injection attacks.

## Best Practices

1. **Use Appropriate Limits**: Set reasonable limits to avoid overwhelming clients with too many results.
2. **Leverage Sorting**: Use sorting to present the most relevant results first.
3. **Combine Filters**: Use `search_documents` and `search_directories` to narrow down results.
4. **Handle Empty Results**: Always check for empty result sets in client code.
5. **Pagination**: For large result sets, consider implementing pagination on the client side with multiple requests using different limits and offsets (though offset is not currently supported).

## Future Enhancements

Potential improvements for future versions:

1. **Pagination Support**: Add `offset` parameter for pagination.
2. **Advanced Filters**: Filter by file type, date ranges, size ranges.
3. **Full-Text Search**: Search within document content, not just names.
4. **Search Scoping**: Limit search to specific directories or paths.
5. **Search History**: Track and suggest previous search queries.
6. **Relevance Scoring**: Implement relevance-based sorting.
