import os
from mlx_lm import convert

os.environ["HF_TOKEN"] = "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"

def generate_new_model_name(model_id: str, target_org:str) -> str:
    org, name = model_id.split("/")
    base, ext = os.path.splitext(name)
    new_name = f"{base}-mlx-4bit{ext}"
    new_model_id = f"{target_org}/{new_name}"
    return new_model_id

if __name__ == "__main__":
    target_org = "p988744"
    repo = "openai/gpt-oss-120b"
    upload_repo = generate_new_model_name(repo, target_org)
    convert(repo, quantize=True, upload_repo=upload_repo, mlx_path=f"./output/{upload_repo.replace('/', '_')}")