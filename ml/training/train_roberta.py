"""
Script de fine-tuning de RoBERTa para clasificación de riesgo de salud mental.
Uso: python -m ml.training.train_roberta --data_path ml/data/processed/train.csv --epochs 5
"""

import argparse
import os
import json
import numpy as np
import pandas as pd
from datetime import datetime
from loguru import logger

import torch
from torch.utils.data import Dataset, DataLoader
from torch.optim import AdamW
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    get_linear_schedule_with_warmup,
)
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold


# === Dataset ===

class MentalHealthDataset(Dataset):
    """Dataset para textos etiquetados con nivel de riesgo."""

    def __init__(self, texts, labels, tokenizer, max_length=512):
        self.texts = texts
        self.labels = labels
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, idx):
        text = str(self.texts[idx])
        label = self.labels[idx]
        encoding = self.tokenizer(
            text,
            add_special_tokens=True,
            max_length=self.max_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )
        return {
            "input_ids": encoding["input_ids"].flatten(),
            "attention_mask": encoding["attention_mask"].flatten(),
            "label": torch.tensor(label, dtype=torch.long),
        }


# === Entrenamiento ===

def train_epoch(model, data_loader, optimizer, scheduler, device):
    model.train()
    total_loss = 0
    correct = 0
    total = 0

    for batch in data_loader:
        optimizer.zero_grad()
        input_ids = batch["input_ids"].to(device)
        attention_mask = batch["attention_mask"].to(device)
        labels = batch["label"].to(device)

        outputs = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
        loss = outputs.loss
        logits = outputs.logits

        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()
        scheduler.step()

        total_loss += loss.item()
        preds = torch.argmax(logits, dim=1)
        correct += (preds == labels).sum().item()
        total += labels.size(0)

    return total_loss / len(data_loader), correct / total


def evaluate(model, data_loader, device):
    model.eval()
    total_loss = 0
    all_preds = []
    all_labels = []
    all_probs = []

    with torch.no_grad():
        for batch in data_loader:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = batch["label"].to(device)

            outputs = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
            total_loss += outputs.loss.item()

            probs = torch.softmax(outputs.logits, dim=1)
            preds = torch.argmax(probs, dim=1)

            all_preds.extend(preds.cpu().numpy())
            all_labels.extend(labels.cpu().numpy())
            all_probs.extend(probs.cpu().numpy())

    all_preds = np.array(all_preds)
    all_labels = np.array(all_labels)
    all_probs = np.array(all_probs)

    metrics = {
        "loss": total_loss / len(data_loader),
        "accuracy": (all_preds == all_labels).mean(),
        "f1_weighted": f1_score(all_labels, all_preds, average="weighted"),
        "f1_macro": f1_score(all_labels, all_preds, average="macro"),
        "precision_weighted": precision_score(all_labels, all_preds, average="weighted"),
        "recall_weighted": recall_score(all_labels, all_preds, average="weighted"),
        "classification_report": classification_report(
            all_labels, all_preds,
            target_names=["bajo", "medio", "alto"],
            output_dict=True,
        ),
        "confusion_matrix": confusion_matrix(all_labels, all_preds).tolist(),
    }

    # AUC-ROC (one-vs-rest)
    try:
        metrics["auc_roc"] = roc_auc_score(all_labels, all_probs, multi_class="ovr")
    except ValueError:
        metrics["auc_roc"] = 0.0

    return metrics


# === Main ===

def main():
    parser = argparse.ArgumentParser(description="Fine-tuning RoBERTa para salud mental")
    parser.add_argument("--data_path", type=str, required=True, help="Ruta al CSV de entrenamiento")
    parser.add_argument("--model_name", type=str, default="bertin-project/bertin-roberta-base-spanish", help="Modelo base de HuggingFace")
    parser.add_argument("--output_dir", type=str, default="ml/data/models/roberta-finetuned")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--learning_rate", type=float, default=2e-5)
    parser.add_argument("--max_length", type=int, default=512)
    parser.add_argument("--kfold", type=int, default=5, help="Folds para validación cruzada")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Dispositivo: {device}")

    # Cargar datos
    df = pd.read_csv(args.data_path)
    logger.info(f"Dataset: {len(df)} muestras")
    logger.info(f"Distribución:\n{df['label'].value_counts()}")

    texts = df["text"].values
    labels = df["label"].values  # 0=bajo, 1=medio, 2=alto

    # Tokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)

    # Validación cruzada k-fold
    skf = StratifiedKFold(n_splits=args.kfold, shuffle=True, random_state=42)
    fold_metrics = []

    for fold, (train_idx, val_idx) in enumerate(skf.split(texts, labels)):
        logger.info(f"\n=== Fold {fold + 1}/{args.kfold} ===")

        train_dataset = MentalHealthDataset(texts[train_idx], labels[train_idx], tokenizer, args.max_length)
        val_dataset = MentalHealthDataset(texts[val_idx], labels[val_idx], tokenizer, args.max_length)

        train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True)
        val_loader = DataLoader(val_dataset, batch_size=args.batch_size)

        # Modelo fresco para cada fold
        model = AutoModelForSequenceClassification.from_pretrained(
            args.model_name, num_labels=3
        ).to(device)

        optimizer = AdamW(model.parameters(), lr=args.learning_rate, weight_decay=0.01)
        total_steps = len(train_loader) * args.epochs
        scheduler = get_linear_schedule_with_warmup(optimizer, num_warmup_steps=int(0.1 * total_steps), num_training_steps=total_steps)

        best_f1 = 0
        patience = 2
        patience_counter = 0

        for epoch in range(args.epochs):
            train_loss, train_acc = train_epoch(model, train_loader, optimizer, scheduler, device)
            val_metrics = evaluate(model, val_loader, device)

            logger.info(
                f"Epoch {epoch+1}/{args.epochs} - "
                f"Train Loss: {train_loss:.4f}, Train Acc: {train_acc:.4f} | "
                f"Val Loss: {val_metrics['loss']:.4f}, Val F1: {val_metrics['f1_weighted']:.4f}, "
                f"Val AUC: {val_metrics['auc_roc']:.4f}"
            )

            # Early stopping
            if val_metrics["f1_weighted"] > best_f1:
                best_f1 = val_metrics["f1_weighted"]
                patience_counter = 0
                if fold == 0:  # Guardar solo el mejor modelo del primer fold
                    # Guardar en carpeta temporal para evitar conflicto con
                    # archivos abiertos por el backend en Windows
                    tmp_dir = args.output_dir + "_tmp"
                    os.makedirs(tmp_dir, exist_ok=True)
                    model.save_pretrained(tmp_dir)
                    tokenizer.save_pretrained(tmp_dir)
                    # Mover a destino final
                    import shutil
                    if os.path.exists(args.output_dir):
                        shutil.rmtree(args.output_dir, ignore_errors=True)
                    shutil.move(tmp_dir, args.output_dir)
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    logger.info(f"Early stopping en epoch {epoch+1}")
                    break

        fold_metrics.append(val_metrics)

    # Resumen de validación cruzada
    avg_f1 = np.mean([m["f1_weighted"] for m in fold_metrics])
    std_f1 = np.std([m["f1_weighted"] for m in fold_metrics])
    avg_auc = np.mean([m["auc_roc"] for m in fold_metrics])

    logger.info(f"\n=== RESULTADOS VALIDACIÓN CRUZADA ({args.kfold}-fold) ===")
    logger.info(f"F1-Score Weighted: {avg_f1:.4f} ± {std_f1:.4f}")
    logger.info(f"AUC-ROC: {avg_auc:.4f}")
    logger.info(f"Modelo guardado en: {args.output_dir}")

    # Guardar métricas
    report = {
        "model": args.model_name,
        "kfold": args.kfold,
        "epochs": args.epochs,
        "avg_f1_weighted": round(avg_f1, 4),
        "std_f1_weighted": round(std_f1, 4),
        "avg_auc_roc": round(avg_auc, 4),
        "fold_details": [{k: v for k, v in m.items() if k != "classification_report"} for m in fold_metrics],
        "timestamp": datetime.now().isoformat(),
    }
    os.makedirs(args.output_dir, exist_ok=True)
    with open(os.path.join(args.output_dir, "training_report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)


if __name__ == "__main__":
    main()
