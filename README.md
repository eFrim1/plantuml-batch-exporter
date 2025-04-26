# batch-export-plantuml

A script that extracts every `@startuml … @enduml` diagram from a source file and exports each one as a PNG image. It can optionally run a local PlantUML server using Docker.

## Requirements

- Python 3.8+
- `requests` Python package
- Docker (only if using `--docker`)

## Usage

Basic export using the public PlantUML server:

```bash
python batch_export.py diagrams.puml
```

Start a local PlantUML server in Docker automatically:

```bash
python batch_export.py diagrams.puml --docker
```

Output PNG files are saved to the current directory ./exported . Use `-o <DIR>` to specify a different output folder.

## Options

```
-o, --output DIR      Output directory (default: current directory)
--docker              Start a local Docker container for PlantUML
-p, --port PORT       Host port for the Docker container (default: 18080)
-i, --image IMAGE     Docker image to use (default: plantuml/plantuml-server)
-s, --server URL      Use an existing PlantUML/Kroki server
-m, --method MODE     Transport method: AUTO (default), POST, or GET
```

If `--server` and `--docker` are not specified, the script uses `https://www.plantuml.com/plantuml`.

## License

MIT License (see `LICENSE`).
