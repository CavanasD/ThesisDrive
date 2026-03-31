# GitHub Actions Workflows

## test.yml - Automated Testing

This workflow runs the pytest test suite automatically when:
- Code is pushed to any branch
- A pull request is opened or updated

### What it does:
1. Sets up a Python environment (tests on Python 3.13 and 3.14)
2. Installs project dependencies and test requirements
3. Creates necessary directories for the server
4. Runs the full test suite with pytest
5. Uploads test results and logs as artifacts (retained for 7 days)

### Configuration:
- **Timeout**: 10 minutes per test run
- **Matrix testing**: Tests across Python 3.13 and 3.14
- **Artifacts**: Test cache and server logs are uploaded for debugging

### Viewing Results:
- Check the "Actions" tab in the GitHub repository
- Test results will show pass/fail status for each Python version
- Download artifacts to review detailed logs if tests fail
