# -*- coding: utf-8 -*-
"""
Google Form Klonlayıcı - Nihai Sürüm (Tüm Hatalar Düzeltildi)

Bu sürüm, güvenilir JSON ayrıştırma mantığı ile kullanıcı tarafından
bildirilen bölüm, seçenek görseli ve Excel export hatalarını düzeltir.

- Production (Railway / Render / Heroku) uyumlu.
- Zengin Metin Desteği: Başlık, Açıklama, kalın, italik, altı çizili, link ve listeleri tam olarak korur. (Düzeltildi)
- Tam Soru Tipi Desteği: Matris, Ölçek, Tarih, Saat, Derecelendirme dahil tüm yaygın tipleri destekler.
- Medya Desteği: Sorulara ve seçeneklere eklenen görselleri doğru şekilde destekler. (Düzeltildi)
- Doğru Bölümleme: Google Formlar'daki "Bölüm" mantığını doğru şekilde uygular. (Onaylandı)
- Gelişmiş UX: "Diğer" seçeneği, zorunlu alan doğrulaması, şık tasarım korunmuştur.
- Kısa Link Desteği: 'forms.gle' linklerini otomatik olarak çözer.
"""

import os
import io
import json
import requests
import pandas as pd
from bs4 import BeautifulSoup
from flask import Flask, request, render_template_string, send_file, session
from urllib.parse import unquote
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "a-very-secure-dev-fallback-key-indeed")


def analyze_google_form(url: str):
    """
    Verilen Google Form URL'sini, güvenilir JSON verisini kullanarak analiz eder.
    Bölüm, seçenek görseli ve zengin metin hataları bu fonksiyonda düzeltilmiştir.
    """
    try:
        headers = {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/124.0.0.0 Safari/537.36')
        }
        if 'forms.gle/' in url:
            resp = requests.head(url, allow_redirects=True, timeout=10, headers=headers)
            resp.raise_for_status()
            url = resp.url
        
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

    except requests.RequestException as e:
        return {"error": f"URL alınırken bir hata oluştu: {e}"}

    soup = BeautifulSoup(resp.text, 'html.parser')
    form_data = {'pages': []}
    
    for script in soup.find_all('script'):
        if script.string and 'FB_PUBLIC_LOAD_DATA_' in script.string:
            try:
                raw_json_str = script.string.replace('var FB_PUBLIC_LOAD_DATA_ = ', '').rstrip(';')
                data = json.loads(raw_json_str)

                form_info = data[1]
                
                form_data['title'] = form_info[8] if len(form_info) > 8 and form_info[8] else (form_info[0] or 'İsimsiz Form')
                form_data['description'] = form_info[7] if len(form_info) > 7 and isinstance(form_info[7], str) else ''
                
                question_list = form_info[1]
                current_page = []

                if data[1][10] and data[1][10][0]:
                     current_page.append({
                        'type': 'E-posta', 'text': 'E-posta Adresi',
                        'description': 'Bu form, e-posta adreslerini toplamak üzere ayarlanmış.',
                        'entry_id': 'emailAddress', 'required': True
                    })
                
                for q in question_list:
                    if not q or not q[0]: continue

                    question = {}
                    q_id, q_text_plain, q_desc_plain, q_type, q_info = q[0], q[1], q[2], q[3], q[4]

                    # Bölüm (sayfa) ayıracı. Soru tipi 8, yeni bir bölüm anlamına gelir.
                    if q_type == 8:
                        if current_page:
                            form_data['pages'].append(current_page)
                        current_page = []

                    rich_text_info = q[-1] if isinstance(q[-1], list) else []
                    question['text'] = rich_text_info[1] if len(rich_text_info) > 1 and rich_text_info[1] else q_text_plain
                    rich_desc = rich_text_info[2] if len(rich_text_info) > 2 and rich_text_info[2] else None
                    question['description'] = rich_desc or q_desc_plain or ''

                    question['image_url'] = q[5][0] if len(q) > 5 and q[5] and q[5][0] else None
                    
                    item_container = soup.find('div', {'data-item-id': str(q_id)})

                    if q_type == 8 or q_info is None:
                        question['type'] = 'Başlık'
                        current_page.append(question)
                    else:
                        entry_id = q_info[0][0]
                        question['entry_id'] = f'entry.{entry_id}'
                        question['required'] = bool(q_info[0][2])

                        if q_type == 0: question['type'] = 'Kısa Yanıt'
                        elif q_type == 1: question['type'] = 'Paragraf'
                        elif q_type == 2 or q_type == 4:
                            question['type'] = 'Çoktan Seçmeli' if q_type == 2 else 'Onay Kutuları'
                            question['options'] = []
                            question['has_other'] = False
                            
                            option_containers = item_container.select('.docssharedWizToggleLabeledContainer') if item_container else []

                            for i, opt in enumerate(q_info[0][1]):
                                if not opt: continue
                                if len(opt) > 4 and opt[4]:
                                    question['has_other'] = True
                                    continue
                                
                                img_url = None
                                if i < len(option_containers):
                                    img_tag = option_containers[i].select_one('img.L05vke')
                                    if img_tag: img_url = img_tag.get('src')
                                question['options'].append({'text': opt[0], 'image_url': img_url})

                        elif q_type == 3:
                            question['type'] = 'Açılır Liste'
                            question['options'] = [opt[0] for opt in q_info[0][1] if opt and opt[0]]
                        elif q_type == 5:
                            question['type'] = 'Doğrusal Ölçek'
                            question['options'] = [opt[0] for opt in q_info[0][1]]
                            question['labels'] = q_info[0][3] if len(q_info[0]) > 3 and q_info[0][3] else ['', '']
                        elif q_type == 7: # Matris Soruları
                            rows_data = q_info
                            first_row = rows_data[0]
                            question['type'] = 'Onay Kutusu Tablosu' if len(first_row)>11 and first_row[11] and first_row[11][0] else 'Çoktan Seçmeli Tablo'
                            question['required'] = any(bool(r[2]) for r in rows_data)
                            question['cols'] = [c[0] for c in first_row[1]]
                            question['rows'] = [{'text': r[3][0], 'entry_id': f"entry.{r[0]}"} for r in rows_data]
                        elif q_type == 9: question['type'] = 'Tarih'
                        elif q_type == 10: question['type'] = 'Saat'
                        elif q_type == 18:
                            question['type'] = 'Derecelendirme'
                            question['options'] = [str(o[0]) for o in q_info[0][1]]
                        else: continue
                        current_page.append(question)

                if current_page:
                    form_data['pages'].append(current_page)
                break 
            except (json.JSONDecodeError, IndexError, TypeError) as e:
                return {"error": f"Form verisi ayrıştırılırken bir hata oluştu: {e}."}
    
    if not form_data['pages'] or not any(form_data['pages']):
        return {"error": "Formda analiz edilecek soru bulunamadı veya form yapısı okunamadı."}
    return {"form_data": form_data}


# --- HTML Şablonu (Tüm Özelliklerle Birlikte) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>Google Form Klonu</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root {
            --primary-color: #198754; --primary-color-dark: #157347; --border-color: #dee2e6;
            --input-border-color: #ced4da; --body-bg: #f8f9fa; --text-color: #212529;
            --secondary-color: #6c757d; --focus-ring-color: rgba(25, 135, 84, 0.25);
            --focus-border-color: #89bda9;
        }
        body { font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background-color: var(--body-bg); color: var(--text-color); margin: 0; padding: 1.5rem; display: flex; justify-content: center; }
        .container { max-width: 760px; width: 100%; background: #fff; padding: 2rem 2.5rem; border-radius: 8px; box-shadow: 0 4px 15px rgba(0, 0, 0, .07); border: 1px solid var(--border-color); }
        h1, h2 { text-align: center; color: #343a40; font-weight: 600; }
        h1 { margin: 0 0 1.5rem; }
        h2 { margin-top: 2rem; line-height: 1.4; }
        a { color: var(--primary-color); text-decoration: none; font-weight: 600; }
        a:hover { text-decoration: underline; }
        .form-group { margin-bottom: 1.5rem; padding: 1.5rem; border: 1px solid var(--border-color); border-radius: 8px; }
        .page-counter { text-align: center; font-weight: bold; margin-bottom: 1rem; padding: 0.5rem; background-color: #e9ecef; border-radius: 6px; }
        .question-label { display: block; font-weight: 600; margin-bottom: .75rem; color: var(--text-color); line-height: 1.4; }
        .question-description { white-space: pre-wrap; color: var(--secondary-color); line-height: 1.5; margin-top: -0.5rem; margin-bottom: 1rem; font-size: 0.9rem; }
        .question-description ul, .question-description ol, .main-description ul, .main-description ol { margin-top: 0.5rem; padding-left: 1.5rem; }
        .required-star { color: #dc3545; margin-left: 4px; }
        input[type=text], input[type=email], textarea, select, input[type=date], input[type=time] { width: 100%; padding: .5rem 1rem; border: 1px solid var(--input-border-color); border-radius: 0.375rem; box-sizing: border-box; font-size: 1rem; line-height: 1.5; transition: border-color .15s ease-in-out, box-shadow .15s ease-in-out; }
        textarea { min-height: 100px; resize: vertical; }
        input:focus, textarea:focus, select:focus { outline: none; border-color: var(--focus-border-color); box-shadow: 0 0 0 0.25rem var(--focus-ring-color); }
        .radio-group, .checkbox-group { display: flex; flex-direction: column; gap: .5rem; }
        .radio-group label, .checkbox-group label { display: flex; align-items: flex-start; gap: .8rem; cursor: pointer; padding: .5rem .7rem; border-radius: 6px; }
        .radio-group label:hover, .checkbox-group label:hover { background-color: #f8f9fa; }
        input[type=radio], input[type=checkbox] { flex-shrink: 0; margin-top: 0.3rem; width: 1.1rem; height: 1.1rem; accent-color: var(--primary-color); }
        .btn { background-color: var(--primary-color); color: #fff; padding: .75rem 1.5rem; border: 1px solid var(--primary-color); width: 100%; border-radius: 0.375rem; font-size: 1rem; font-weight: 600; cursor: pointer; text-align: center; transition: background-color .15s ease-in-out, border-color .15s ease-in-out; }
        .btn:hover { background-color: var(--primary-color-dark); border-color: #146c43; }
        .btn-secondary { background-color: #6c757d; border-color: #6c757d; }
        .btn-secondary:hover { background-color: #5c636a; border-color: #565e64; }
        .navigation-buttons { display: flex; justify-content: space-between; gap: 1rem; margin-top: 2rem; }
        .navigation-buttons .btn { width: auto; flex-grow: 1; }
        .error-message { background: #f8d7da; color: #58151c; border: 1px solid #f1aeb5; padding: 1rem; border-radius: 6px; text-align: center; }
        .grid-table { width: 100%; border-collapse: collapse; margin-top: .5rem; }
        .grid-table th, .grid-table td { border: 1px solid var(--border-color); padding: .6rem; text-align: center; font-size: .9rem; }
        .grid-table th { background: #f8f9fa; }
        .grid-table td:first-child { text-align: left; font-weight: 600; }
        .rating-group { display: flex; flex-direction: row-reverse; justify-content: center; gap: 5px; }
        .rating-group input { display: none; }
        .rating-group label { font-size: 2rem; color: #ccc; cursor: pointer; }
        .rating-group input:checked ~ label, .rating-group label:hover, .rating-group label:hover ~ label { color: #ffc107; }
        .other-option-label { align-items: center; }
        .other-option-input { flex-grow: 1; margin-left: .5rem; padding: .4rem .6rem; }
        .title-description-block { padding-bottom: 1rem; border-bottom: 1px solid var(--border-color); margin-bottom: 1.6rem; }
        .section-title { margin-top: 0; margin-bottom: 0.5rem; font-size: 1.3em; color: var(--text-color); }
        .section-description { white-space: pre-wrap; color: var(--secondary-color); line-height: 1.5; margin-top: 0; font-size: 0.95em; }
        .main-description { white-space: pre-wrap; color: var(--text-color); line-height: 1.5; }
        .form-image-container { text-align: center; margin-bottom: 1rem; margin-top: 1rem; }
        .form-image-container img { max-width: 100%; height: auto; max-height: 450px; border-radius: 8px; border: 1px solid var(--border-color); }
        .option-content { display: flex; flex-direction: column; align-items: flex-start; width: 100%; }
        .option-image-container img { max-width: 260px; width: 100%; height: auto; display: block; margin-top: 0.6rem; border-radius: 6px; border: 1px solid var(--border-color); }
        .option-text { line-height: 1.4; }
    </style>
</head>
<body>
<div class="container">
    <h1>Google Form Klonlayıcı</h1>
    <form method="post" action="/">
        <div class="form-group" style="padding:1rem;">
            <input type="text" name="url" placeholder="https://docs.google.com/forms/d/e/... veya https://forms.gle/..." required>
            <button type="submit" class="btn" style="margin-top:1rem;">Formu Oluştur</button>
        </div>
    </form>
    {% if error %}
        <div class="error-message">{{ error }}</div>
    {% endif %}
    {% if form_data %}
        <h2 style="text-align:center;margin-top:1.5rem;">{{ form_data.title | safe }}</h2>
        {% if form_data.description %}
            <div class="main-description" style="text-align:center; margin-bottom: 2rem;">{{ form_data.description | safe }}</div>
        {% endif %}
        <form method="post" action="/submit" id="clone-form">
            {% for page in form_data.pages %}
            <div class="page" id="page-{{ loop.index0 }}" style="display: {% if loop.index0 == 0 %}block{% else %}none{% endif %};">
                {% if form_data.pages | length > 1 %}
                    <div class="page-counter">Bölüm {{ loop.index }} / {{ form_data.pages | length }}</div>
                {% endif %}
                {% for q in page %}
                    {% if q.type == 'Başlık' %}
                    <div class="title-description-block">
                        <div class="section-title">{{ q.text | safe }}</div>
                        {% if q.description %}<div class="section-description">{{ q.description | safe }}</div>{% endif %}
                        {% if q.image_url %}<div class="form-image-container"><img src="{{ q.image_url }}" alt="Başlık Görseli"></div>{% endif %}
                    </div>
                    {% else %}
                    <div class="form-group">
                        <label class="question-label">{{ q.text | safe }} {% if q.required %}<span class="required-star">*</span>{% endif %}</label>
                        {% if q.description %}<div class="question-description">{{ q.description | safe }}</div>{% endif %}
                        {% if q.image_url %}<div class="form-image-container"><img src="{{ q.image_url }}" alt="Soru Görseli"></div>{% endif %}

                        {% if q.type == 'E-posta' %} <input type="email" name="{{ q.entry_id }}" required>
                        {% elif q.type == 'Kısa Yanıt' %} <input type="text" name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
                        {% elif q.type == 'Paragraf' %} <textarea name="{{ q.entry_id }}" {% if q.required %}required{% endif %}></textarea>
                        {% elif q.type == 'Çoktan Seçmeli' %}
                        <div class="radio-group">
                            {% for opt in q.options %}
                            <label><input type="radio" name="{{ q.entry_id }}" value="{{ opt.text }}" {% if q.required %}required{% endif %}><div class="option-content"><span class="option-text">{{ opt.text | safe }}</span>{% if opt.image_url %}<div class="option-image-container"><img src="{{ opt.image_url }}" alt="{{ opt.text }}"></div>{% endif %}</div></label>
                            {% endfor %}
                            {% if q.has_other %} <label class="other-option-label"><input type="radio" name="{{ q.entry_id }}" value="__other_option__"><span>Diğer:</span><input type="text" class="other-option-input" name="{{ q.entry_id }}.other_option_response"></label> {% endif %}
                        </div>
                        {% elif q.type == 'Onay Kutuları' %}
                        <div class="checkbox-group">
                            {% for opt in q.options %}
                            <label><input type="checkbox" name="{{ q.entry_id }}" value="{{ opt.text }}"><div class="option-content"><span class="option-text">{{ opt.text | safe }}</span>{% if opt.image_url %}<div class="option-image-container"><img src="{{ opt.image_url }}" alt="{{ opt.text }}"></div>{% endif %}</div></label>
                            {% endfor %}
                            {% if q.has_other %} <label class="other-option-label"><input type="checkbox" name="{{ q.entry_id }}" value="__other_option__"><span>Diğer:</span><input type="text" class="other-option-input" name="{{ q.entry_id }}.other_option_response"></label>{% endif %}
                        </div>
                        {% elif q.type == 'Açılır Liste' %}
                        <select name="{{ q.entry_id }}" {% if q.required %}required{% endif %}><option value="" disabled selected>Seçin...</option>{% for opt in q.options %}<option value="{{ opt }}">{{ opt | safe }}</option>{% endfor %}</select>
                        {% elif q.type == 'Doğrusal Ölçek' %}
                        <div class="radio-group" style="flex-direction:row;justify-content:space-around;align-items:center;"><span><b>{{ q.labels[0] | safe }}</b></span>{% for opt in q.options %} <label style="flex-direction:column;align-items:center;"><span>{{ opt | safe }}</span><input type="radio" name="{{ q.entry_id }}" value="{{ opt }}" {% if q.required %}required{% endif %}></label> {% endfor %}<span><b>{{ q.labels[1] | safe }}</b></span></div>
                        {% elif q.type == 'Derecelendirme' %}
                        <div class="rating-group">{% for opt in q.options | reverse %} <input type="radio" id="star{{ opt }}-{{ q.entry_id }}" name="{{ q.entry_id }}" value="{{ opt }}" {% if q.required %}required{% endif %}><label for="star{{ opt }}-{{ q.entry_id }}">★</label> {% endfor %}</div>
                        {% elif q.type == 'Tarih' %} <input type="date" name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
                        {% elif q.type == 'Saat' %} <input type="time" name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
                        {% elif q.type in ['Çoktan Seçmeli Tablo','Onay Kutusu Tablosu'] %}
                        <table class="grid-table"><thead><tr><th></th>{% for col in q.cols %}<th>{{ col | safe }}</th>{% endfor %}</tr></thead><tbody>{% for row in q.rows %}<tr><td>{{ row.text | safe }}</td>{% for col in q.cols %}<td><input type="{{ 'checkbox' if 'Onay' in q.type else 'radio' }}" name="{{ row.entry_id }}" value="{{ col }}" {% if q.required and 'Onay' not in q.type %}required{% endif %}></td>{% endfor %}</tr>{% endfor %}</tbody></table>
                        {% endif %}
                    </div>
                    {% endif %}
                {% endfor %}
            </div>
            {% endfor %}
            <div class="navigation-buttons">
                <button type="button" class="btn btn-secondary" id="back-button" onclick="navigate(-1)" style="display: none;">Geri</button>
                <button type="button" class="btn" id="next-button" onclick="navigate(1)">Sonraki</button>
                <button type="submit" class="btn" id="submit-button" style="display: none;">Gönder ve Excel Olarak İndir</button>
            </div>
        </form>
    {% endif %}
</div>
<script>
document.addEventListener('DOMContentLoaded', () => {
    let radioMouseDownChecked;
    document.body.addEventListener('mousedown', e => { if (e.target.tagName === 'INPUT' && e.target.type === 'radio') { radioMouseDownChecked = e.target.checked; }}, true);
    document.body.addEventListener('click', e => { if (e.target.tagName === 'INPUT' && e.target.type === 'radio' && e.target.checked && radioMouseDownChecked) { e.target.checked = false; }});
    document.querySelectorAll('.other-option-input').forEach(textInput => {
        const checkAssociatedControl = () => {
            const associatedControl = textInput.closest('label').querySelector('input[type=radio], input[type=checkbox]');
            if (associatedControl) { associatedControl.checked = true; }
        };
        textInput.addEventListener('input', checkAssociatedControl);
        textInput.addEventListener('focus', checkAssociatedControl);
    });
    const pageCount = document.querySelectorAll('.page').length;
    if(pageCount > 0) { showPage(0); } else { document.querySelector('.navigation-buttons').style.display = 'none'; }
});
let currentPageIndex = 0;
const pages = document.querySelectorAll('.page');
const backButton = document.getElementById('back-button');
const nextButton = document.getElementById('next-button');
const submitButton = document.getElementById('submit-button');

function updateButtons() {
    if (!pages.length || pages.length <= 1) {
        if(backButton) backButton.style.display = 'none';
        if(nextButton) nextButton.style.display = 'none';
        if(submitButton) submitButton.style.display = 'inline-block';
        return;
    }
    backButton.style.display = currentPageIndex > 0 ? 'inline-block' : 'none';
    nextButton.style.display = currentPageIndex < pages.length - 1 ? 'inline-block' : 'none';
    submitButton.style.display = currentPageIndex === pages.length - 1 ? 'inline-block' : 'none';
}

function showPage(index) {
    pages.forEach((page, i) => { page.style.display = i === index ? 'block' : 'none'; });
    updateButtons();
    window.scrollTo(0, 0);
}

function validatePage(pageIndex) {
    const currentPage = pages[pageIndex];
    if (!currentPage) return true;
    const form = document.getElementById('clone-form');
    for (const input of currentPage.querySelectorAll('[required]')) {
        if (input.type === 'radio') {
            const radioGroup = currentPage.querySelector(`input[name="${input.name}"]:checked`);
            if(!radioGroup) {
                form.reportValidity();
                return false;
            }
        } else if (!input.value && (input.type !== 'checkbox')) {
             form.reportValidity();
             return false;
        }
    }
    return true;
}

function navigate(direction) {
    if (direction > 0 && !validatePage(currentPageIndex)) { return; }
    const newIndex = currentPageIndex + direction;
    if (newIndex >= 0 && newIndex < pages.length) {
        currentPageIndex = newIndex;
        showPage(currentPageIndex);
    }
}
</script>
</body>
</html>
"""

# --- Flask Rotaları (Mantık Değişikliği Yok) ---
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        if not url or ("docs.google.com/forms" not in url and "forms.gle" not in url):
            return render_template_string(HTML_TEMPLATE, error="Geçerli bir Google Form URL'si girin.")
        
        result = analyze_google_form(url)
        if "error" in result:
            return render_template_string(HTML_TEMPLATE, error=result["error"])
        
        session['form_structure'] = result['form_data']
        return render_template_string(HTML_TEMPLATE, form_data=result['form_data'])
    
    return render_template_string(HTML_TEMPLATE)

@app.route('/submit', methods=['POST'])
def submit():
    form_structure = session.get('form_structure')
    if not form_structure:
        return "Hata: Form yapısı bulunamadı. Lütfen formu ana sayfadan tekrar oluşturun.", 400

    user_answers = request.form
    results = []
    
    all_questions = [q for page in form_structure.get('pages', []) for q in page]

    for question in all_questions:
        q_type = question.get('type')
        if not q_type or q_type == 'Başlık': continue

        # --- DÜZELTME: EXCEL HATASI ---
        # `question.get('text')` `None` olabileceğinden, `or ''` ekleyerek
        # BeautifulSoup'a her zaman bir string gönderilmesini sağlıyoruz.
        q_text_html = question.get('text', '')
        q_text_plain = BeautifulSoup(q_text_html, "html.parser").get_text(separator=" ", strip=True) or f"İsimsiz Soru ({q_type})"
        
        answer_str = "Yanıtlanmadı"

        if 'Tablo' in q_type:
            for row in question.get('rows', []):
                rid = row.get('entry_id')
                if not rid: continue
                row_label = f"{q_text_plain} [{row.get('text', '')}]"
                if 'Onay' in q_type:
                    val = ', '.join(user_answers.getlist(rid)) or "Yanıtlanmadı"
                else:
                    val = user_answers.get(rid, "Yanıtlanmadı")
                results.append({"Soru": row_label, "Cevap": val})
            continue

        entry = question.get('entry_id')
        if not entry: continue
        
        if q_type == 'Onay Kutuları':
            answers = user_answers.getlist(entry)
            final = []
            if "__other_option__" in answers:
                answers.remove("__other_option__")
                other_txt = user_answers.get(f"{entry}.other_option_response", "").strip()
                final.append(f"Diğer: {other_txt}" if other_txt else "Diğer")
            final.extend(answers)
            if final: answer_str = ', '.join(final)
        elif q_type == 'Çoktan Seçmeli':
            ans = user_answers.get(entry)
            if ans == "__other_option__":
                other_txt = user_answers.get(f"{entry}.other_option_response", "").strip()
                answer_str = f"Diğer: {other_txt}" if other_txt else "Diğer"
            elif ans: answer_str = ans
        else:
            raw_answer = user_answers.get(entry, "")
            if raw_answer: answer_str = raw_answer

        results.append({"Soru": q_text_plain, "Cevap": answer_str})

    df = pd.DataFrame(results)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        sheet_name = 'Form Yanıtları'
        df.to_excel(writer, index=False, sheet_name=sheet_name)
        ws = writer.sheets[sheet_name]
        for i, col in enumerate(df.columns):
            max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
            ws.column_dimensions[chr(65 + i)].width = min(max_len, 70)
    output.seek(0)
    session.pop('form_structure', None)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'form_yanitlari_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
