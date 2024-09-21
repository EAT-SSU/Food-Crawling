# Set the base directory for the layer
$layerDir = ".\python-requirements-layer"

# Create layer directory
Remove-Item -Path $layerDir -Recurse -ErrorAction SilentlyContinue
New-Item -Path $layerDir\python -ItemType Directory -Force

# Export requirements from Poetry (optional, if you still want to keep it for reference)
poetry export -f requirements.txt --output $layerDir\requirements.txt --without-hashes

# Install packages to the layer directory using pip
python -m pip install -r $layerDir\requirements.txt -t $layerDir\python\lib\python3.9\site-packages

# Clean up
Remove-Item -Path $layerDir\requirements.txt
