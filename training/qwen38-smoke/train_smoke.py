import torch
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer
from peft import LoraConfig, get_peft_model

MODEL = "/opt/workdev/training/models/Qwen3.8-4B-Distill"
DATA = "/opt/workdev/training/qwen38-smoke/data/train.jsonl"
OUT = "/opt/workdev/training/qwen38-smoke/output"

print("1. Carregando tokenizer...")
tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)

if tok.pad_token is None:
    tok.pad_token = tok.eos_token

print("2. Carregando dataset...")
ds = load_dataset("json", data_files=DATA, split="train")

def preprocess(row):
    text = tok.apply_chat_template(
        row["messages"],
        tokenize=False,
        add_generation_prompt=False,
    )
    enc = tok(
        text,
        truncation=True,
        max_length=512,
        padding="max_length",
    )
    enc["labels"] = enc["input_ids"].copy()
    return enc

ds = ds.map(preprocess, remove_columns=ds.column_names)

print("3. Carregando modelo em CPU...")
model = AutoModelForCausalLM.from_pretrained(
    MODEL,
    dtype=torch.float32,
    trust_remote_code=True,
    low_cpu_mem_usage=True,
)

print("4. Aplicando LoRA...")
lora = LoraConfig(
    r=4,
    lora_alpha=8,
    lora_dropout=0.05,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    task_type="CAUSAL_LM",
)

model = get_peft_model(model, lora)
model.print_trainable_parameters()

args = TrainingArguments(
    output_dir=OUT,
    max_steps=1,
    per_device_train_batch_size=1,
    gradient_accumulation_steps=1,
    learning_rate=1e-4,
    logging_steps=1,
    save_steps=1,
    save_total_limit=1,
    report_to="none",
    use_cpu=True,
)

print("5. Iniciando 1 step...")
trainer = Trainer(
    model=model,
    args=args,
    train_dataset=ds,
)

trainer.train()

print("6. Salvando adapter...")
model.save_pretrained(OUT + "/adapter")
tok.save_pretrained(OUT + "/adapter")

print("SMOKE TRAIN OK")
