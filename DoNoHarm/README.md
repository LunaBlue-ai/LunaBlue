# DoNoHarm Knowledge Base

Welcome to the DoNoHarm directory! This folder contains markdown files that are automatically loaded into LunaBlueAI's context during initialization.

## Purpose

These knowledge base files help LunaBlueAI:
- Maintain consistent, helpful, and safe responses
- Understand contextual guidelines and values
- Make appropriate decisions about sensitive topics
- Provide well-informed and balanced outputs

## Structure

Each markdown file in this directory is loaded into memory and made available to LunaBlueAI. The system reads and maintains these files throughout the session, using them to inform all responses.

## Adding Your Own Guidelines

1. Create a new `.md` file in this directory
2. Write your guidelines, values, or knowledge in standard Markdown format
3. Restart LunaBlueAI or reload to incorporate the new content

## Default Files

The following starter files are included:
- `guidelines.md` - Usage guidelines and content policies
- `values.md` - Core principles and values

Feel free to customize these files or add new ones to match your specific needs and requirements.

## Example

A sample knowledge base entry might look like:

```markdown
# Custom Guidelines

## Policy on Data Privacy
LunaBlueAI should always respect user privacy and:
- Never store personal information unnecessarily
- Encrypt sensitive data
- Follow GDPR and similar regulations
```

After adding this file, LunaBlueAI will reference it when handling privacy-related requests.
