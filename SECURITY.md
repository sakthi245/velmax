# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.3.x   | :white_check_mark: |
| < 0.3   | :x:                |

## Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security issue, please report it responsibly.

### How to Report

**Do not** create a public GitHub issue for security vulnerabilities.

Instead, please email us at: **security@velmax.example.com**

Include the following information:
- Description of the vulnerability
- Steps to reproduce (if possible)
- Affected versions
- Potential impact
- Any suggested fixes (if you have them)

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 7 days
- **Fix Timeline**: Depends on severity
  - Critical: Within 7 days
  - High: Within 14 days
  - Medium: Within 30 days
  - Low: Next release cycle

### Disclosure Policy

- We will coordinate with you on disclosure timing
- We aim to disclose vulnerabilities after a fix is available
- Credit will be given to reporters (unless you prefer anonymity)

## Security Best Practices for Users

### API Keys
- Store API keys in environment variables, not in code
- Use `.env` files (gitignored) for local development
- Rotate keys regularly

### Network Security
- Use HTTPS for all external requests
- Validate SSL certificates (default enabled)
- Configure timeouts to prevent hanging connections

### Rate Limiting
- Respect target site rate limits
- Configure appropriate delays between requests
- Monitor for 429 responses and back off

### Data Handling
- Don't scrape PII without explicit consent
- Encrypt sensitive data at rest
- Sanitize output before logging

## Known Security Considerations

### Engine Security
- **Firecrawl/Apify**: Cloud adapters send HTML to external services
- **Playwright**: Executes JavaScript in isolated browser contexts
- **HTTP engines**: No JavaScript execution, lower attack surface

### Local Execution
- Generated scripts run in subprocess with limited permissions
- Sandbox execution when possible
- Validate all user input before passing to engines

## Third-Party Dependencies

We regularly update dependencies via Dependabot. Critical vulnerabilities trigger immediate patch releases.

To check for vulnerabilities locally:
```bash
pip install safety
safety check
```

## Contact

For security-related questions or concerns, contact:
- **Email**: security@velmax.example.com
- **PGP Key**: Available on request

---

*This policy is adapted from common open-source security practices.*