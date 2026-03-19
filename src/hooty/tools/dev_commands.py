"""Shared dev tool command whitelist for CodingTools and PowerShellTools."""

DEV_TOOL_COMMANDS: list[str] = [
    # General
    "git", "make", "docker", "docker-compose",
    # Python
    "python", "python3", "pip", "pip3", "uv", "ruff", "pytest", "mypy", "pyright",
    # JavaScript / TypeScript
    "node", "npm", "npx", "yarn", "pnpm", "bun", "deno", "tsc", "tsx",
    # Java
    "java", "javac", "mvn", "mvnw", "gradle", "gradlew",
    # Go
    "go", "gofmt", "gopls",
    # Rust
    "cargo", "rustc", "rustup", "rustfmt",
    # C / C++
    "gcc", "g++", "clang", "clang++", "cmake", "ninja",
    # Ruby
    "ruby", "gem", "bundle", "rake",
    # .NET
    "dotnet",
]
