# -*- coding: utf-8 -*-
"""
Google Form Klonlayıcı
Production (Railway / Render / Heroku) uyumlu.
- SECRET_KEY .env / ortam değişkeninden okunur
- Gunicorn ile çalıştırılabilir
- Google Form verisini çekip yeniden oluşturur ve cevapları Excel indirir
- Başlık/Açıklama bölümlerini ve soru açıklamalarını destekler
- Kalın, italik, altı çizili, link ve liste gibi zengin metin formatlarını korur
- Sorulara ve seçeneklere eklenen görselleri destekler (Yeniden düzenlenmiş hibrit yaklaşım)
- KULLANICI GERİ BİLDİRİM DÜZELTMELERİ UYGULANDI:
  - FIX: "Diğer" seçeneğinin metin alanına yazıldığında otomatik olarak işaretlenmesi sağlandı.
  - FIX: Çoktan seçmeli seçeneklerin (radyo düğmeleri) tekrar tıklanarak seçiminin kaldırılması sağlandı.
  - INFO: Soru sırası, Google Form'un dahili veri yapısındaki sırayla birebir aynıdır.
"""

import os
import io
import json
import requests
import pandas as pd
from bs4 import BeautifulSoup
from flask import Flask, request, render_template_string, send_file, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-fallback-key")  # .env yoksa fallback

def get_inner_html(element):
    """Bir BeautifulSoup elementinin iç HTML'ini string olarak döndürür."""
    if not element:
        return ""
    return "".join(map(str, element.contents)).strip()

def analyze_google_form(url: str):
    """Google Form URL'sini parse ederek zengin metin ve görselleri içeren soru yapısını döndürür."""
    try:
        headers = {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
        }

        # ================== BAŞLANGIÇ: YENİ EKLENEN KOD (Kısaltılmış Link Çözücü) ==================
        # Eğer URL kısaltılmış bir 'forms.gle' linki ise, önce gerçek adresi bul.
        if "forms.gle/" in url:
            try:
                # 'allow_redirects=True' (varsayılan) ile istek göndererek yönlendirmeyi takip et.
                # 'timeout' ekleyerek sonsuz döngü veya yavaş bağlantıları önle.
                head_response = requests.head(url, allow_redirects=True, timeout=10, headers=headers)
                head_response.raise_for_status()
                url = head_response.url  # Yönlendirmenin sonundaki nihai URL'yi al.
            except requests.exceptions.RequestException as e:
                return {"error": f"Kısaltılmış URL çözülemedi. Linkin çalıştığından emin olun. Hata: {e}"}
        # ================== BİTİŞ: YENİ EKLENEN KOD ==================

        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        return {"error": f"URL okunamadı. Geçerli bir Google Form linki girin. Hata: {e}"}

    soup = BeautifulSoup(response.text, 'html.parser')
    form_data = {"questions": []}

    title_div = soup.find('div', class_='F9yp7e')
    form_data['title'] = get_inner_html(title_div) if title_div else "İsimsiz Form"
    desc_div = soup.find('div', class_='cBGGJ')
    form_data['description'] = get_inner_html(desc_div) if desc_div else ""

    for script in soup.find_all('script'):
        if script.string and 'FB_PUBLIC_LOAD_DATA_' in script.string:
            try:
                raw = script.string.replace('var FB_PUBLIC_LOAD_DATA_ = ', '').rstrip(';')
                data = json.loads(raw)
                question_list = data[1][1]

                for q_data in question_list:
                    try:
                        item_id = q_data[0]
                        q_type = q_data[3]
                        question = {'image_url': None}

                        item_container = soup.find('div', {'data-item-id': str(item_id)})

                        q_text_html = q_data[1]
                        q_desc_html = q_data[2] if len(q_data) > 2 and q_data[2] else ""
                        
                        if item_container:
                            title_elem = item_container.find(class_='meSK8 M7eMe')
                            desc_elem = item_container.find(class_='spb5Rd OIC90c')
                            if title_elem:
                                q_text_html = get_inner_html(title_elem)
                            if desc_elem:
                                q_desc_html = get_inner_html(desc_elem)
                            
                            img_elem = item_container.select_one('.y6GzNb img')
                            if img_elem and img_elem.has_attr('src'):
                                question['image_url'] = img_elem.get('src')

                        question['text'] = q_text_html
                        question['description'] = q_desc_html

                        if q_type == 6:
                            question['type'] = 'Başlık'
                            form_data['questions'].append(question)
                            continue

                        if q_type == 7:
                            question['type'] = 'Çoktan Seçmeli Tablo'
                            rows_data = q_data[4]
                            if not (isinstance(rows_data, list) and rows_data): continue
                            first_row = rows_data[0]
                            question['type'] = 'Onay Kutusu Tablosu' if len(first_row) > 11 and first_row[11] and first_row[11][0] else 'Çoktan Seçmeli Tablo'
                            question['required'] = bool(first_row[2])
                            question['cols'] = [c[0] for c in first_row[1]]
                            question['rows'] = [{'text': r[3][0], 'entry_id': f"entry.{r[0]}"} for r in rows_data]
                            form_data['questions'].append(question)
                            continue

                        q_info = q_data[4][0]
                        question['entry_id'] = f"entry.{q_info[0]}"
                        question['required'] = bool(q_info[2])

                        if q_type == 0: question['type'] = 'Kısa Yanıt'
                        elif q_type == 1: question['type'] = 'Paragraf'
                        elif q_type in (2, 4):
                            question['options'] = []
                            question['has_other'] = False
                            if q_info[1]:
                                option_html_elements = item_container.select('.docssharedWizToggleLabeledContainer') if item_container else []
                                
                                for i, opt in enumerate(q_info[1]):
                                    if len(opt) > 4 and opt[4]:
                                        question['has_other'] = True
                                        continue
                                    if not opt[0]: continue

                                    opt_text = opt[0]
                                    opt_image_url = None
                                    if i < len(option_html_elements):
                                        img_tag = option_html_elements[i].select_one('.LAANW img.QU5LQc')
                                        if img_tag and img_tag.has_attr('src'):
                                            opt_image_url = img_tag.get('src')
                                    
                                    question['options'].append({'text': opt_text, 'image_url': opt_image_url})
                            question['type'] = 'Çoktan Seçmeli' if q_type == 2 else 'Onay Kutuları'
                        elif q_type == 3:
                            question['type'] = 'Açılır Liste'
                            question['options'] = [o[0] for o in q_info[1] if o[0]]
                        elif q_type == 5:
                            question['type'] = 'Doğrusal Ölçek'
                            question['options'] = [o[0] for o in q_info[1]]
                            question['labels'] = q_info[3] if len(q_info) > 3 and q_info[3] else ["", ""]
                        elif q_type == 18:
                            question['type'] = 'Derecelendirme'
                            question['options'] = [str(o[0]) for o in q_info[1]]
                        elif q_type == 9: question['type'] = 'Tarih'
                        elif q_type == 10: question['type'] = 'Saat'
                        else: continue

                        form_data['questions'].append(question)
                    except (IndexError, TypeError, KeyError) as e:
                        print(f"DEBUG: Bir soru işlenirken hata oluştu (ID: {q_data[0]}). Soru atlanıyor. Hata: {e}")
                        continue
                break
            except (json.JSONDecodeError, IndexError, TypeError) as e:
                return {"error": f"Form verileri ayrıştırılamadı (format değişmiş olabilir). Hata: {e}"}

    email_div = soup.find('div', {'jsname': 'Y0xS1b'})
    if email_div:
        try:
            parent = email_div.find_parent('div', {'jsmodel': 'CP1oW'})
            if parent and parent.has_attr('data-params'):
                p = parent['data-params']
                entry_id_part = p.split(',')[-1].split('"')[0]
                if entry_id_part.isdigit():
                    form_data['questions'].insert(0, {
                        'text': 'E-posta', 'description': 'Lütfen geçerli bir e-posta adresi girin.',
                        'type': 'E-posta', 'entry_id': f'entry.{entry_id_part}',
                        'required': True, 'image_url': None
                    })
        except Exception: pass

    if not form_data['questions']:
        return {"error": "Formda analiz edilecek soru veya içerik bulunamadı."}
    return form_data


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="tr"><head><meta charset="UTF-8"><title>Google Form Klonlayıcı</title>
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<style>
:root {
    --bs-green: #198754;
    --bs-dark-green: #157347;
    --bs-border-color: #dee2e6;
    --bs-input-border-color: #ced4da;
    --bs-body-bg: #f8f9fa;
    --bs-body-color: #212529;
    --bs-secondary-color: #6c757d;
    --bs-focus-ring-color: rgba(13, 110, 253, 0.25);
    --bs-focus-border-color: #86b7fe;
}
body{
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", "Noto Sans", "Liberation Sans", Arial, sans-serif;
    background-color: var(--bs-body-bg);
    color: var(--bs-body-color);
    margin:0;
    padding:2rem;
    display:flex;
    justify-content:center;
}
.container{
    max-width:760px;
    width:100%;
    background:#fff;
    padding:2rem 2.5rem;
    border-radius:8px;
    box-shadow:0 4px 15px rgba(0,0,0,.07);
    border: 1px solid var(--bs-border-color);
}
h1, h2{text-align:center;color:#343a40;font-weight:600;}
h1{margin:0 0 1rem}
h2{margin-top:2rem;}
a {color: var(--bs-green); text-decoration: underline;}
a:hover {text-decoration: none;}
.form-group{
    margin-bottom:1.5rem;
    padding:1.5rem;
    border:1px solid var(--bs-border-color);
    border-radius:8px;
}
.question-label{
    display:block;
    font-weight:600;
    margin-bottom:.75rem;
    color: var(--bs-body-color);
    line-height:1.4;
}
.question-description{
    white-space:pre-wrap;
    color: var(--bs-secondary-color);
    line-height:1.5;
    margin-top:-0.5rem;
    margin-bottom:1rem;
    font-size:0.9rem;
}
.question-description ul,.question-description ol{margin-top:0.5rem;padding-left:1.5rem;}
.required-star{color:#dc3545;margin-left:4px}
input[type=text],input[type=email],textarea,select,input[type=date],input[type=time]{
    width:100%;
    padding:.5rem 1rem;
    border:1px solid var(--bs-input-border-color);
    border-radius: 0.375rem;
    box-sizing:border-box;
    font-size:1rem;
    line-height: 1.5;
    transition: border-color .15s ease-in-out, box-shadow .15s ease-in-out;
}
textarea{min-height:100px;resize:vertical}
input:focus,textarea:focus,select:focus{
    outline:none;
    border-color: var(--bs-focus-border-color);
    box-shadow:0 0 0 0.25rem var(--bs-focus-ring-color);
}
.radio-group,.checkbox-group{display:flex;flex-direction:column;gap:.5rem}
.radio-group label,.checkbox-group label{display:flex;align-items:flex-start;gap:.8rem;cursor:pointer;padding:.5rem .7rem;border-radius:6px}
.radio-group label:hover,.checkbox-group label:hover{background-color: #f8f9fa;}
input[type=radio],input[type=checkbox]{flex-shrink:0;margin-top:0.3rem;width:1.1rem;height:1.1rem;accent-color: var(--bs-green);}
.btn{
    background-color: var(--bs-green);
    color:#fff;
    padding:.75rem 1.5rem;
    border:1px solid var(--bs-green);
    width:100%;
    border-radius: 0.375rem;
    font-size:1rem;
    font-weight:600;
    cursor:pointer;
    text-align: center;
    transition: background-color .15s ease-in-out, border-color .15s ease-in-out;
}
.btn:hover{
    background-color: var(--bs-dark-green);
    border-color: #146c43;
}
.error-message{background:#f8d7da;color:#58151c;border: 1px solid #f1aeb5;padding:1rem;border-radius:6px;text-align:center}
.grid-table{width:100%;border-collapse:collapse;margin-top:.5rem}
.grid-table th,.grid-table td{border:1px solid var(--bs-border-color);padding:.6rem;text-align:center;font-size:.9rem}
.grid-table th{background:#f8f9fa}
.grid-table td:first-child{text-align:left;font-weight:600}
.rating-group{display:flex;flex-direction:row-reverse;justify-content:center;gap:5px}
.rating-group input{display:none}
.rating-group label{font-size:2rem;color:#ccc;cursor:pointer}
.rating-group input:checked ~ label,.rating-group label:hover,.rating-group label:hover ~ label{color:#ffc107}
.other-option-label{align-items:center}
.other-option-input{flex-grow:1;margin-left: .5rem; padding:.4rem .6rem}
.title-description-block{padding-bottom:1rem;border-bottom:1px solid var(--bs-border-color);margin-bottom:1.6rem}
.section-title{margin-top:0;margin-bottom:0.5rem;font-size:1.3em;color:var(--bs-body-color);}
.section-description{white-space:pre-wrap;color:var(--bs-secondary-color);line-height:1.5;margin-top:0;font-size:0.95em}
.main-description{white-space:pre-wrap;color: var(--bs-secondary-color); line-height:1.5;}
.main-description ul,.main-description ol{margin-top:0.5rem;padding-left:1.5rem;}
.form-image-container{text-align:center;margin-bottom:1rem;margin-top:1rem;}
.form-image-container img{max-width:100%;height:auto;max-height:450px;border-radius:8px;border:1px solid var(--bs-border-color);}
.option-content{display:flex;flex-direction:column;align-items:flex-start;width:100%}
.option-image-container img{max-width:260px;width:100%;height:auto;display:block;margin-bottom:0.6rem;border-radius:6px;border:1px solid var(--bs-border-color);}
.option-text{line-height:1.4}
</style></head>
<body><div class="container">
<h1>Google Form Klonlayıcı</h1>
<form method="post" action="/"><div class="form-group" style="padding:1rem;">
<input type="text" name="url" placeholder="https://docs.google.com/forms/d/e/... veya https://forms.gle/..." required>
<button type="submit" class="btn" style="margin-top:1rem;">Formu Oluştur</button>
</div></form>
{% if error %}<div class="error-message">{{ error }}</div>{% endif %}
{% if form_data %}
<h2 style="text-align:center;margin-top:1.5rem; line-height: 1.4;">{{ form_data.title | safe }}</h2>
{% if form_data.description %}<div class="main-description">{{ form_data.description | safe }}</div>{% endif %}
<form method="post" action="/submit">
{% for q in form_data.questions %}
    {% if q.type == 'Başlık' %}
    <div class="title-description-block">
        <div class="section-title">{{ q.text | safe }}</div>
        {% if q.description %}<div class="section-description">{{ q.description | safe }}</div>{% endif %}
        {% if q.image_url %}<div class="form-image-container"><img src="{{ q.image_url }}" alt="Başlık Görseli"></div>{% endif %}
    </div>
    {% else %}
    <div class="form-group">
        <div class="question-label">{{ q.text | safe }} {% if q.required %}<span class="required-star">*</span>{% endif %}</div>
        {% if q.description %}<div class="question-description">{{ q.description | safe }}</div>{% endif %}
        {% if q.image_url %}<div class="form-image-container"><img src="{{ q.image_url }}" alt="Soru Görseli"></div>{% endif %}

        {% if q.type == 'E-posta' %} <input type="email" name="{{ q.entry_id }}" required>
        {% elif q.type == 'Kısa Yanıt' %} <input type="text" name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
        {% elif q.type == 'Paragraf' %} <textarea name="{{ q.entry_id }}" {% if q.required %}required{% endif %}></textarea>
        {% elif q.type == 'Çoktan Seçmeli' %}
        <div class="radio-group">
        {% for opt in q.options %}
        <label>
            <input type="radio" name="{{ q.entry_id }}" value="{{ opt.text }}" {% if q.required %}required{% endif %}>
            <div class="option-content">
                {% if opt.image_url %}<div class="option-image-container"><img src="{{ opt.image_url }}" alt="{{ opt.text }}"></div>{% endif %}
                <span class="option-text">{{ opt.text }}</span>
            </div>
        </label>
        {% endfor %}
        {% if q.has_other %} <label class="other-option-label"><input type="radio" name="{{ q.entry_id }}" value="__other_option__"><span>Diğer:</span><input type="text" class="other-option-input" name="{{ q.entry_id }}.other_option_response"></label> {% endif %}
        </div>
        {% elif q.type == 'Onay Kutuları' %}
        <div class="checkbox-group">
        {% for opt in q.options %}
        <label>
            <input type="checkbox" name="{{ q.entry_id }}" value="{{ opt.text }}">
            <div class="option-content">
                {% if opt.image_url %}<div class="option-image-container"><img src="{{ opt.image_url }}" alt="{{ opt.text }}"></div>{% endif %}
                <span class="option-text">{{ opt.text }}</span>
            </div>
        </label>
        {% endfor %}
        {% if q.has_other %} <label class="other-option-label"><input type="checkbox" name="{{ q.entry_id }}" value="__other_option__"><span>Diğer:</span><input type="text" class="other-option-input" name="{{ q.entry_id }}.other_option_response"></label>{% endif %}
        </div>
        {% elif q.type == 'Açılır Liste' %}
        <select name="{{ q.entry_id }}" {% if q.required %}required{% endif %}><option value="" disabled selected>Seçin...</option>
        {% for opt in q.options %}<option value="{{ opt }}">{{ opt }}</option>{% endfor %}</select>
        {% elif q.type == 'Doğrusal Ölçek' %}
        <div class="radio-group" style="flex-direction:row;justify-content:space-around;align-items:center;">
        <span>{{ q.labels[0] }}</span>
        {% for opt in q.options %} <label style="flex-direction:column;align-items:center;"><span>{{ opt }}</span><input type="radio" name="{{ q.entry_id }}" value="{{ opt }}" {% if q.required %}required{% endif %}></label> {% endfor %}
        <span>{{ q.labels[1] }}</span></div>
        {% elif q.type == 'Derecelendirme' %}
        <div class="rating-group">
        {% for opt in q.options | reverse %} <input type="radio" id="star{{ opt }}-{{ q.entry_id }}" name="{{ q.entry_id }}" value="{{ opt }}" {% if q.required %}required{% endif %}><label for="star{{ opt }}-{{ q.entry_id }}">★</label> {% endfor %}
        </div>
        {% elif q.type == 'Tarih' %} <input type="date" name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
        {% elif q.type == 'Saat' %} <input type="time" name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
        {% elif q.type in ['Çoktan Seçmeli Tablo','Onay Kutusu Tablosu'] %}
        <table class="grid-table"><thead><tr><th></th>
        {% for col in q.cols %}<th>{{ col }}</th>{% endfor %}</tr></thead><tbody>
        {% for row in q.rows %}<tr><td>{{ row.text }}</td>
        {% for col in q.cols %}<td><input type="{{ 'checkbox' if 'Onay' in q.type else 'radio' }}" name="{{ row.entry_id }}" value="{{ col }}" {% if q.required %}required{% endif %}></td>{% endfor %}
        </tr>{% endfor %}</tbody></table>
        {% endif %}
    </div>
    {% endif %}
{% endfor %}
<button type="submit" class="btn">Gönder ve Excel Olarak İndir</button>
</form>
{% endif %}
</div>
<script>
document.addEventListener('DOMContentLoaded', () => {
    let radioMouseDownChecked;
    document.body.addEventListener('mousedown', e => {
        if (e.target.tagName === 'INPUT' && e.target.type === 'radio') {
            radioMouseDownChecked = e.target.checked;
        }
    }, true);
    document.body.addEventListener('click', e => {
        if (e.target.tagName === 'INPUT' && e.target.type === 'radio' && radioMouseDownChecked) {
            e.target.checked = false;
        }
    });
    document.querySelectorAll('.other-option-input').forEach(textInput => {
        const checkAssociatedControl = () => {
            const associatedControl = textInput.closest('label').querySelector('input[type=radio], input[type=checkbox]');
            if (associatedControl) {
                associatedControl.checked = true;
            }
        };
        textInput.addEventListener('input', checkAssociatedControl);
        textInput.addEventListener('focus', checkAssociatedControl);
    });
});
</script>
</body></html>
"""

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        if not url or ("docs.google.com/forms" not in url and "forms.gle" not in url):
            return render_template_string(HTML_TEMPLATE, error="Geçerli bir Google Form URL'si girin.")
        form_data = analyze_google_form(url)
        if "error" in form_data:
            return render_template_string(HTML_TEMPLATE, error=form_data["error"])
        session['form_structure'] = form_data
        return render_template_string(HTML_TEMPLATE, form_data=form_data)
    return render_template_string(HTML_TEMPLATE)

@app.route('/submit', methods=['POST'])
def submit():
    form_structure = session.get('form_structure')
    if not form_structure:
        return "Hata: Form yapısı bulunamadı. Lütfen formu ana sayfadan tekrar oluşturun.", 400

    user_answers = request.form
    results = []

    for question in form_structure['questions']:
        q_type = question['type']
        
        if q_type == 'Başlık':
            continue

        q_text_plain = BeautifulSoup(question['text'], "html.parser").get_text(separator=" ", strip=True)

        if 'Tablo' in q_type:
            for row in question['rows']:
                rid = row['entry_id']
                row_label = f"{q_text_plain} [{row['text']}]"
                if 'Onay' in q_type:
                    answers = user_answers.getlist(rid)
                    val = ', '.join(answers) if answers else "Boş Bırakıldı"
                else:
                    val = user_answers.get(rid, "Boş Bırakıldı")
                results.append({"Soru": row_label, "Soru Tipi": q_type, "Cevap": val})
            continue

        entry = question.get('entry_id')
        answer_str = "Boş Bırakıldı"

        if q_type == 'Onay Kutuları':
            answers = user_answers.getlist(entry)
            final = []
            if "__other_option__" in answers:
                answers.remove("__other_option__")
                other_txt = user_answers.get(f"{entry}.other_option_response", "").strip()
                final.append(f"Diğer: {other_txt}" if other_txt else "Diğer (belirtilmemiş)")
            final.extend(answers)
            if final: answer_str = ', '.join(final)
        elif q_type == 'Çoktan Seçmeli':
            ans = user_answers.get(entry)
            if ans == "__other_option__":
                other_txt = user_answers.get(f"{entry}.other_option_response", "").strip()
                answer_str = f"Diğer: {other_txt}" if other_txt else "Diğer (belirtilmemiş)"
            elif ans:
                answer_str = ans
        else:
            raw_answer = user_answers.get(entry, "")
            answer_str = raw_answer if raw_answer.strip() != "" else "Boş Bırakıldı"


        results.append({"Soru": q_text_plain, "Soru Tipi": q_type, "Cevap": answer_str})

    df = pd.DataFrame(results)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        sheet = 'Form Cevaplari'
        df.to_excel(writer, index=False, sheet_name=sheet)
        ws = writer.sheets[sheet]
        for i, col in enumerate(df.columns):
            col_width = max(df[col].astype(str).map(len).max(), len(col))
            ws.column_dimensions[chr(65 + i)].width = min(col_width + 2, 70)
    output.seek(0)
    session.pop('form_structure', None)
    return send_file(output,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True,
                     download_name='form_cevaplari.xlsx')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
