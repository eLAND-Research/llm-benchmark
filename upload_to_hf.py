import os

from huggingface_hub import HfApi


os.environ["HF_TOKEN"] = "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"
api = HfApi(token=os.getenv("HF_TOKEN"))
api.upload_folder(
    folder_path="output/p988744_gpt-oss-20b-mlx-4bit",
    repo_id="eland-information/gpt-oss-20b-mlx-4bit",
    repo_type="model",
)