#!/usr/bin/env python3
"""
Генератор графиков спроса и предложения для задания 21.

Создаёт PNG-изображения для каждого задания из task21_questions.json.
Графики показывают кривые спроса (D) и предложения (S) с соответствующим
сдвигом одной из кривых.
"""

import json
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np


# Пути
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
QUESTIONS_FILE = os.path.join(PROJECT_ROOT, 'task21', 'task21_questions.json')
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'data', 'images')


def generate_graph(task_data: dict, output_path: str) -> None:
    """
    Генерирует график спроса и предложения для одного задания.

    Args:
        task_data: Данные задания из JSON
        output_path: Путь для сохранения PNG
    """
    curve_shifted = task_data.get('curve_shifted', 'demand')
    shift_direction = task_data.get('shift_direction', 'right')

    fig, ax = plt.subplots(1, 1, figsize=(5, 4.5), dpi=150)
    fig.patch.set_facecolor('white')

    # Базовые точки для кривых
    q = np.linspace(1, 9, 100)

    # Кривая предложения (S): наклон вверх (P = a + b*Q)
    s_base = 1.0 + 0.8 * q

    # Кривая спроса (D): наклон вниз (P = a - b*Q)
    d_base = 9.0 - 0.8 * q

    # Величина сдвига
    shift = 1.8 if shift_direction == 'right' else -1.8

    if curve_shifted == 'demand':
        # Сдвиг спроса
        d_shifted = 9.0 - 0.8 * (q - shift)

        # Рисуем S (неизменная)
        ax.plot(q, s_base, 'b-', linewidth=2.2, label='S')

        # Рисуем D (исходная, пунктиром)
        ax.plot(q, d_base, color='#CC0000', linestyle='--', linewidth=1.5, alpha=0.6, label='D')

        # Рисуем D1 (сдвинутая)
        ax.plot(q, d_shifted, 'r-', linewidth=2.2, label='D₁')

        # Подписи на кривых
        ax.text(8.5, s_base[-5], 'S', fontsize=13, fontweight='bold', color='blue',
                ha='left', va='bottom')
        ax.text(8.5, d_base[-5], 'D', fontsize=13, fontweight='bold', color='#CC0000',
                ha='left', va='center', alpha=0.6)
        ax.text(8.5, d_shifted[-5], 'D₁', fontsize=13, fontweight='bold', color='red',
                ha='left', va='top')

        # Стрелка показывающая направление сдвига
        if shift_direction == 'right':
            ax.annotate('', xy=(6.5, 4.2), xytext=(5.0, 4.2),
                        arrowprops=dict(arrowstyle='->', color='red', lw=1.8))
        else:
            ax.annotate('', xy=(3.5, 4.2), xytext=(5.0, 4.2),
                        arrowprops=dict(arrowstyle='->', color='red', lw=1.8))

    elif curve_shifted == 'supply':
        # Сдвиг предложения
        s_shifted = 1.0 + 0.8 * (q - shift)

        # Рисуем D (неизменная)
        ax.plot(q, d_base, 'r-', linewidth=2.2, label='D')

        # Рисуем S (исходная, пунктиром)
        ax.plot(q, s_base, color='#0000CC', linestyle='--', linewidth=1.5, alpha=0.6, label='S')

        # Рисуем S1 (сдвинутая)
        ax.plot(q, s_shifted, 'b-', linewidth=2.2, label='S₁')

        # Подписи на кривых
        ax.text(8.5, d_base[-5], 'D', fontsize=13, fontweight='bold', color='red',
                ha='left', va='top')
        ax.text(8.5, s_base[-5], 'S', fontsize=13, fontweight='bold', color='#0000CC',
                ha='left', va='center', alpha=0.6)
        ax.text(8.5, s_shifted[-5], 'S₁', fontsize=13, fontweight='bold', color='blue',
                ha='left', va='bottom')

        # Стрелка показывающая направление сдвига
        if shift_direction == 'right':
            ax.annotate('', xy=(6.5, 4.5), xytext=(5.0, 4.5),
                        arrowprops=dict(arrowstyle='->', color='blue', lw=1.8))
        else:
            ax.annotate('', xy=(3.5, 4.5), xytext=(5.0, 4.5),
                        arrowprops=dict(arrowstyle='->', color='blue', lw=1.8))

    # Оформление осей
    ax.set_xlabel('Q', fontsize=14, fontweight='bold', labelpad=5)
    ax.set_ylabel('P', fontsize=14, fontweight='bold', rotation=0, labelpad=15)

    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)

    # Убираем числовые метки — на ЕГЭ графики без конкретных значений
    ax.set_xticks([])
    ax.set_yticks([])

    # Оси в стиле ЕГЭ — стрелки на концах
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_linewidth(1.5)
    ax.spines['bottom'].set_linewidth(1.5)

    # Стрелки на осях
    ax.annotate('', xy=(10.2, 0), xytext=(0, 0),
                arrowprops=dict(arrowstyle='->', color='black', lw=1.5))
    ax.annotate('', xy=(0, 10.2), xytext=(0, 0),
                arrowprops=dict(arrowstyle='->', color='black', lw=1.5))

    ax.set_title(f'Рынок {task_data.get("market_name", "")}',
                 fontsize=11, pad=10, style='italic')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    plt.close(fig)


def main():
    # Загружаем данные
    with open(QUESTIONS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    tasks = data.get('tasks', [])
    if not tasks:
        print("No tasks found in JSON file")
        sys.exit(1)

    # Создаём директорию если нужно
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Generating graphs for {len(tasks)} tasks...")

    generated = 0
    errors = 0

    for task in tasks:
        task_id = task.get('id', 'unknown')
        image_url = task.get('image_url', '')

        if not image_url:
            print(f"  SKIP {task_id}: no image_url")
            continue

        output_path = os.path.join(PROJECT_ROOT, image_url)

        try:
            generate_graph(task, output_path)
            generated += 1
            print(f"  OK   {task_id} -> {image_url}")
        except Exception as e:
            errors += 1
            print(f"  FAIL {task_id}: {e}")

    print(f"\nDone: {generated} generated, {errors} errors")


if __name__ == '__main__':
    main()
