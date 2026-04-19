# Contributing to LunaBlue

Thank you for your interest in contributing to LunaBlue!

## Getting Started

1. Fork the repository
2. Clone your fork locally
3. Create a feature branch: `git checkout -b feature/your-feature-name`
4. Follow the development setup in [DEVELOPMENT.md](./DEVELOPMENT.md)

## Development Workflow

### Code Standards

- **TypeScript**: Use strict mode, proper typing, and meaningful names
- **Python**: Follow PEP 8 guidelines
- **Formatting**: Use prettier for TypeScript, black for Python
- **Commits**: Write clear, concise commit messages

### Before Submitting

1. Run linting: `npm run lint`
2. Run tests: `npm test`
3. Build: `npm run build`
4. Verify no errors in logs

### Pull Request Process

1. Ensure your branch is up to date with `main`
2. Provide a clear description of changes
3. Reference any related issues
4. Ensure CI checks pass
5. Request review from maintainers

## Areas for Contribution

### High Priority
- [ ] Web UI implementation (Phase 2)
- [ ] Multi-model switching
- [ ] GPU acceleration refinement
- [ ] Test coverage

### Nice to Have
- [ ] Performance optimizations
- [ ] Additional documentation
- [ ] Example scripts that use LunaBlueAI
- [ ] Additional model support

### Documentation
- Improve existing documentation
- Add code examples
- Create tutorials
- Translate documentation

## Guidelines

### Code Quality
- Maintain test coverage
- Follow existing code patterns
- Add comments for complex logic
- Keep functions focused and testable

### Commit Messages
```
Type: Brief description

Longer description if needed, explaining:
- What changed and why
- Any breaking changes
- Related issues
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

### Comments in Code
```typescript
// Use for single-line comments
// Explain the "why", not the "what"

/**
 * Use JSDoc for functions and classes
 * @param text - The prompt text
 * @returns The LLM response
 */
```

## Reporting Issues

If you find a bug, please create an issue with:
- Clear description of the problem
- Steps to reproduce
- Expected vs actual behavior
- Your environment (OS, Node version, etc.)
- Relevant logs

## Feature Requests

To suggest a feature:
- Explain the motivation
- Describe the expected behavior
- Consider edge cases
- Link to related discussions if any

## Code Review Process

- Reviews provide feedback for improvement
- Address comments constructively
- Ask for clarification if needed
- Be patient - maintainers volunteer their time

## License

By contributing to LunaBlue, you agree that your contributions will be licensed under the MIT License.

## Questions?

- Check existing issues and documentation first
- Open an issue with the `question` label
- Join community discussions

Thank you for helping make LunaBlue better!
