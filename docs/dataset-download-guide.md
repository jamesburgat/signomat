# Dataset Download Guide

Create the raw dataset folders first:

```bash
mkdir -p data/training/raw/mapillary
mkdir -p data/training/raw/glare
```

## Mapillary

- Official dataset page: https://www.mapillary.com/dataset/trafficsign
- Paper: https://arxiv.org/abs/1909.04422
- API help: https://help.mapillary.com/hc/en-us/articles/360010234680-Accessing-imagery-and-data-through-the-Mapillary-API
- Object detections help: https://help.mapillary.com/hc/en-us/articles/115000967191-Object-detections
- Official Python SDK: https://github.com/mapillary/mapillary-python-sdk

Notes:

- The paper says the dataset is available for academic research.
- In practice, the dataset page currently requires login.
- Mapillary also supports API and SDK access for object detections and related data workflows.

What to do:

1. Create a Mapillary account.
2. Log in at the dataset page.
3. Accept any research-use or license terms if prompted.
4. Download the traffic sign dataset if your account is granted access, or use the API or SDK workflow.

## GLARE

- Official repo: https://github.com/NicholasCG/GLARE_Dataset
- Paper: https://arxiv.org/abs/2209.08716
- Dataset Drive folder: https://drive.google.com/drive/folders/1gmoOSgvjR4DP7jGfGS_xAmxcMShyeThx?usp=sharing

Notes:

- The repo README says the dataset is released under CC BY 4.0.
- This is the easiest of the three to access directly.

What to do:

1. Open the Google Drive folder.
2. Download the `Images` folder at minimum.
3. Place the images and annotations under `data/training/raw/glare`.

## Recommended Folder Layout

If possible, arrange the files like this:

- `data/training/raw/mapillary/images`
- `data/training/raw/mapillary/annotations`
- `data/training/raw/glare/images`
- `data/training/raw/glare/annotations`

## After Downloading

Run:

```bash
. .venv/bin/activate
python scripts/prepare_sign_training_workspace.py
python scripts/normalize_sign_datasets.py
```

This will:

- inventory what was found
- write the training manifest files
- normalize supported annotations into a unified sign manifest

## Important Notes

- `Mapillary` is the least straightforward right now because access appears gated by login, license, or API workflow.
- `GLARE` is the easiest to obtain directly.

## Sources

- Mapillary dataset paper: https://arxiv.org/abs/1909.04422
- Mapillary dataset page: https://www.mapillary.com/dataset/trafficsign
- Mapillary API help: https://help.mapillary.com/hc/en-us/articles/360010234680-Accessing-imagery-and-data-through-the-Mapillary-API
- Mapillary object detections help: https://help.mapillary.com/hc/en-us/articles/115000967191-Object-detections
- Mapillary SDK: https://github.com/mapillary/mapillary-python-sdk
- GLARE repo: https://github.com/NicholasCG/GLARE_Dataset
- GLARE paper: https://arxiv.org/abs/2209.08716
