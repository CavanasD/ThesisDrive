# CFMS on Websocket

CFMS (Confidential File Management System), is a complete solution for 
managing confidential documents. This is the repository used to 
implement server functionality.

The Project is still in the early stages of development and cannot 
guarantee the security and stability of running the Service. 

Welcome to Github Issues for improvements and bug reports.

You can access the Chinese Simplified version of the development 
documentation here: [CFMS Server Documentation][doc-url] 
However, Since this document was written specifically for the previous 
version of CFMS, much of it may be outdated. If possible, use code 
comments as the primary reference.

[doc-url]: https://cfms-server-doc.readthedocs.io/zh_CN/latest

## Quick Setup

```bash
# Clone repo
git clone https://github.com/creeper19472/cfms_on_websocket.git

# Enter working dir
cd cfms_on_websocket/src

# Setup submodules
git submodule init
git submodule update --depth=1

# Setup dependencies
uv sync --upgrade

# Activate virtual environment
source .venv/bin/activate
```

## Testing

This repository includes an automated test suite built with pytest. Note that
you should finish the installation before running tests.

To run the tests:

```bash
# Install dependencies
uv sync --dev

# Run all tests
uv run pytest

# Run specific test files
uv run pytest tests/test_basic.py
```

For more information about the test suite, see [tests/README.md](tests/README.md).

## Security

We do our utmost to prevent and resolve security issues within our capabilities. 
If you discover any existing vulnerabilities, you are welcome to submit a report 
to us.

## Contributing

This is a project that is under active development and we are looking 
for people interested in the project to participate in testing. We are 
well aware that the system still has huge shortcomings as a functional 
solution – and we want as many people as possible to join in improving 
them.