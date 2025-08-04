# -*- coding: utf-8 -*-
"""
Google Form Klonlayıcı
Production (Railway / Render / Heroku) uyumlu.
SECRET_KEY .env / ortam değişkeninden okunur
Gunicorn ile çalıştırılabilir
Google Form verisini çekip yeniden oluşturur ve cevapları Excel indirir
Başlık/Açıklama bölümlerini ve soru açıklamalarını destekler
Kalın, italik, altı çizili, link ve liste gibi zengin metin formatlarını korur
"""

# Gerekli Kütüphanelerin Yüklenmesi
import os
import io
import json
import requests
import pandas as pd
from bs4 import BeautifulSoup
from flask import Flask, request, render_template_string, send_file, session

# --- 1. FLASK UYGULAMASININ BAŞLATILMASI ---
app = Flask(__name__)
# Production ortamı için ortam değişkeninden, geliştirme ortamı için varsayılan bir anahtar kullanır.
app.secret_key = os.environ.get("SECRET_KEY", "dev-fallback-key")


# --- 2. YARDIMCI FONKSİYONLAR ---

def get_inner_html(element):
    """
    Bir BeautifulSoup elementinin iç HTML'ini string olarak döndürür.
    # NOT: Bu fonksiyon, zengin metin formatlarını (<b>, <i>, <a>) korumak için kritik öneme sahiptir.
    # .get_text() yerine bu kullanılarak etiketler kaybolmaz.
    """
    return "".join(map(str, element.contents)).strip()


# --- 3. ANA FORM ANALİZ FONKSİYONU ---

def analyze_google_form(url: str):
    """Google Form URL'sini parse ederek zengin metin içeren soru yapısını döndürür."""
    try:
        headers = {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        return {"error": f"URL okunamadı. Geçerli bir Google Form linki girin. Hata: {e}"}

    soup = BeautifulSoup(response.text, 'html.parser')
    form_data = {"questions": []}

    # Ana Başlık ve Açıklama (HTML olarak alınır)
    title_div = soup.find('div', class_='F9yp7e')
    form_data['title'] = get_inner_html(title_div) if title_div else "İsimsiz Form"
    desc_div = soup.find('div', class_='cBGGJ')
    form_data['description'] = get_inner_html(desc_div) if desc_div else ""

    # Formun asıl yapısı script etiketindeki JSON verisinden okunur
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
                        question = {}

                        # HTML'den zengin metin içeriğini al
                        item_container = soup.find('div', {'data-item-id': str(item_id)})
                        
                        # Fallback olarak JSON verisindeki metinler
                        q_text_html = q_data[1] 
                        q_desc_html = q_data[2] if len(q_data) > 2 and q_data[2] else ""
                        
                        # Eğer HTML elementi bulunduysa, zengin metni oradan çek
                        if item_container:
                            title_elem = item_container.find(class_='meSK8 M7eMe')
                            desc_elem = item_container.find(class_='spb5Rd OIC90c')
                            if title_elem:
                                # NOT: Burada get_inner_html çağrısı, soru başlığındaki zengin metni korur.
                                q_text_html = get_inner_html(title_elem)
                            if desc_elem:
                                # NOT: Burada get_inner_html çağrısı, soru açıklamasındaki zengin metni korur.
                                q_desc_html = get_inner_html(desc_elem)

                        question['text'] = q_text_html
                        question['description'] = q_desc_html

                        # Soru tiplerine göre yapılandırma
                        if q_type == 6: # Başlık Bölümü
                            question['type'] = 'Başlık'
                            form_data['questions'].append(question)
                            continue

                        if q_type == 7: # Matris Tablosu
                            rows_data = q_data[4]
                            if not (isinstance(rows_data, list) and rows_data): continue
                            
                            is_checkbox_grid = False
                            try:
                                if len(rows_data[0]) > 11 and rows_data[0][11] and rows_data[0][11][0]:
                                    is_checkbox_grid = True
                            except Exception: pass
                            
                            question['type'] = 'Onay Kutusu Tablosu' if is_checkbox_grid else 'Çoktan Seçmeli Tablo'
                            question['required'] = bool(rows_data[0][2])
                            question['cols'] = [c[0] for c in rows_data[0][1]]
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
                                for opt in q_info[1]:
                                    if len(opt) > 4 and opt[4]: question['has_other'] = True
                                    elif opt[0]: question['options'].append(opt[0])
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
                
                except (IndexError, TypeError, KeyError):
                    continue
            break # İlk geçerli script bloğunu bulduktan sonra döngüden çık
        except (json.JSONDecodeError, IndexError, TypeError) as e:
            return {"error": f"Form verileri ayrıştırılamadı (format değişmiş olabilir). Hata: {e}"}

    # E-posta toplama alanı kontrolü
    email_div = soup.find('div', {'jsname': 'Y0xS1b'})
    if email_div:
        try:
            parent = email_div.find_parent('div', {'jsmodel': 'CP1oW'})
            if parent and parent.has_attr('data-params'):
                p = parent['data-params']
                entry_id_part = p.split(',')[-1].split('"')[0]
                if entry_id_part.isdigit():
                    form_data['questions'].insert(0, {
                        'text': 'E-posta',
                        'description': 'Lütfen geçerli bir e-posta adresi girin.',
                        'type': 'E-posta',
                        'entry_id': f'entry.{entry_id_part}',
                        'required': True
                    })
        except Exception: pass

    if not form_data['questions']:
        return {"error": "Formda analiz edilecek soru veya içerik bulunamadı."}
        
    return form_data


# --- 4. HTML ve CSS ŞABLONU ---
# Arayüzü oluşturan HTML, CSS ve Jinja2 şablon kodları
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>Google Form Klonlayıcı</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body{font-family:Arial,sans-serif;background:#f4f7fa;margin:0;padding:2rem;display:flex;justify-content:center}
        .container{max-width:760px;width:100%;background:#fff;padding:2rem 2.2rem;border-radius:12px;box-shadow:0 10px 25px rgba(0,0,0,.08)}
        h1{text-align:center;margin:0 0 1rem}
        .form-group{margin-bottom:1.6rem;padding:1.2rem;border:1px solid #dbe2e9;border-radius:8px;background:#fdfdff}
        .question-label{display:block;font-weight:600;margin-bottom:.9rem}
        .question-description, .section-description, .main-description{white-space:pre-wrap;color:#666;line-height:1.4;margin-bottom:0.9rem;font-size:0.9rem}
        .question-description ul, .question-description ol, .main-description ul, .main-description ol{margin-top:0.5rem;padding-left:1.5rem;}
        .required-star{color:#e74c3c;margin-left:4px}
        input[type=text],input[type=email],textarea,select,input[type=date],input[type=time]{width:100%;padding:.8rem 1rem;border:1px solid #dbe2e9;border-radius:6px;box-sizing:border-box;font-size:1rem}
        textarea{min-height:100px;resize:vertical}
        input:focus,textarea:focus,select:focus{outline:none;border-color:#4a80ff;box-shadow:0 0 0 3px rgba(74,128,255,.2)}
        .radio-group,.checkbox-group{display:flex;flex-direction:column;gap:.6rem}
        .radio-group label,.checkbox-group label{display:flex;align-items:center;gap:.6rem;cursor:pointer;padding:.4rem .5rem;border-radius:6px}
        .radio-group label:hover,.checkbox-group label:hover{background:#f0f4ff}
        input[type=radio],input[type=checkbox]{width:1.1rem;height:1.1rem;accent-color:#4a80ff}
        .btn{background:#4a80ff;color:#fff;padding:.9rem 1.4rem;border:none;width:100%;border-radius:6px;font-size:1.05rem;font-weight:600;cursor:pointer}
        .btn:hover{background:#3c6de0}
        .error-message{background:#e74c3c;color:#fff;padding:1rem;border-radius:6px;text-align:center}
        .grid-table{width:100%;border-collapse:collapse;margin-top:.5rem}
        .grid-table th,.grid-table td{border:1px solid #dbe2e9;padding:.6rem;text-align:center;font-size:.9rem}
        .grid-table th{background:#f8f9fa}
        .grid-table td:first-child{text-align:left;font-weight:600}
        .rating-group{display:flex;flex-direction:row-reverse;justify-content:center;gap:5px}
        .rating-group input{display:none}
        .rating-group label{font-size:2rem;color:#ccc;cursor:pointer}
        .rating-group input:checked ~ label,.rating-group label:hover,.rating-group label:hover ~ label{color:#f39c12}
        .other-option-label{align-items:center}
        .other-option-input{flex-grow:1;padding:.4rem .6rem}
        .title-description-block{padding-bottom:1rem;border-bottom:1px solid #eee;margin-bottom:1.6rem}
        .section-title{margin-top:0;margin-bottom:0.5rem;font-size:1.3em;color:#2c3e50}
        .main-description{line-height:1.5;}
    </style>
</head>
<body>
<div class="container">
    <h1>Google Form Klonlayıcı</h1>
    <form method="post" action="/">
        <div class="form-group" style="padding:0.8rem;">
            <input type="text" name="url" placeholder="https://docs.google.com/forms/d/e/..." required>
            <button type="submit" class="btn" style="margin-top:.8rem;">Formu Oluştur</button>
        </div>
    </form>
    
    {% if error %}
        <div class="error-message">{{ error }}</div>
    {% endif %}

    {% if form_data %}
        <!-- NOT: 'safe' filtresi, HTML etiketlerinin (<b>, <a> vb.) çalışmasını sağlar. -->
        <h2 style="text-align:center;margin-top:1.5rem;">{{ form_data.title | safe }}</h2>
        {% if form_data.description %}<div class="main-description">{{ form_data.description | safe }}</div>{% endif %}
        
        <form method="post" action="/submit">
            {% for q in form_data.questions %}
                {% if q.type == 'Başlık' %}
                    <div class="title-description-block">
                        <div class="section-title">{{ q.text | safe }}</div>
                        {% if q.description %}<div class="section-description">{{ q.description | safe }}</div>{% endif %}
                    </div>
                {% else %}
                    <div class="form-group">
                        <label class="question-label">{{ q.text | safe }} {% if q.required %}<span class="required-star">*</span>{% endif %}</label>
                        {% if q.description %}<div class="question-description">{{ q.description | safe }}</div>{% endif %}

                        {% if q.type == 'E-posta' %}
                            <input type="email" name="{{ q.entry_id }}" required>
                        {% elif q.type == 'Kısa Yanıt' %}
                            <input type="text" name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
                        {% elif q.type == 'Paragraf' %}
                            <textarea name="{{ q.entry_id }}" {% if q.required %}required{% endif %}></textarea>
                        {% elif q.type == 'Çoktan Seçmeli' %}
                            <div class="radio-group">
                                {% for opt in q.options %}
                                    <label><input type="radio" name="{{ q.entry_id }}" value="{{ opt }}" {% if q.required %}required{% endif %}><span>{{ opt }}</span></label>
                                {% endfor %}
                                {% if q.has_other %}
                                    <label class="other-option-label"><input type="radio" name="{{ q.entry_id }}" value="__other_option__"><span>Diğer:</span><input type="text" class="other-option-input" name="{{ q.entry_id }}.other_option_response"></label>
                                {% endif %}
                            </div>
                        {% elif q.type == 'Onay Kutuları' %}
                            <div class="checkbox-group">
                                {% for opt in q.options %}
                                    <label><input type="checkbox" name="{{ q.entry_id }}" value="{{ opt }}"><span>{{ opt }}</span></label>
                                {% endfor %}
                                {% if q.has_other %}
                                    <label class="other-option-label"><input type="checkbox" name="{{ q.entry_id }}" value="__other_option__"><span>Diğer:</span><input type="text" class="other-option-input" name="{{ q.entry_id }}.other_option_response"></label>
                                {% endif %}
                            </div>
                        {% elif q.type == 'Açılır Liste' %}
                            <select name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
                                <option value="" disabled selected>Seçin...</option>
                                {% for opt in q.options %}<option value="{{ opt }}">{{ opt }}</option>{% endfor %}
                            </select>
                        {% elif q.type == 'Doğrusal Ölçek' %}
                            <div class="radio-group" style="flex-direction:row;justify-content:space-around;align-items:center;">
                                <span>{{ q.labels[0] }}</span>
                                {% for opt in q.options %}
                                    <label style="flex-direction:column;"><span>{{ opt }}</span><input type="radio" name="{{ q.entry_id }}" value="{{ opt }}" {% if q.required %}required{% endif %}></label>
                                {% endfor %}
                                <span>{{ q.labels[1] }}</span>
                            </div>
                        {% elif q.type == 'Derecelendirme' %}
                            <div class="rating-group">
                                {% for opt in q.options | reverse %}
                                    <input type="radio" id="star{{ opt }}-{{ q.entry_id }}" name="{{ q.entry_id }}" value="{{ opt }}" {% if q.required %}required{% endif %}><label for="star{{ opt }}-{{ q.entry_id }}">★</label>
                                {% endfor %}
                            </div>
                        {% elif q.type == 'Tarih' %}
                            <input type="date" name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
                        {% elif q.type == 'Saat' %}
                            <input type="time" name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
                        {% elif q.type in ['Çoktan Seçmeli Tablo','Onay Kutusu Tablosu'] %}
                            <table class="grid-table">
                                <thead><tr><th></th>{% for col in q.cols %}<th>{{ col }}</th>{% endfor %}</tr></thead>
                                <tbody>
                                {% for row in q.rows %}
                                    <tr>
                                        <td>{{ row.text }}</td>
                                        {% for col in q.cols %}
                                            <td><input type="{{ 'checkbox' if 'Onay' in q.type else 'radio' }}" name="{{ row.entry_id }}" value="{{ col }}" {% if q.required %}required{% endif %}></td>
                                        {% endfor %}
                                    </tr>
                                {% endfor %}
                                </tbody>
                            </table>
                        {% endif %}
                    </div>
                {% endif %}
            {% endfor %}
            <button type="submit" class="btn">Gönder ve Excel Olarak İndir</button>
        </form>
    {% endif %}
</div>
</body>
</html>
"""


# --- 5. FLASK ROUTE (URL) TANIMLAMALARI ---

@app.route('/', methods=['GET', 'POST'])
def index():
    """Ana sayfa. URL girme formunu gösterir ve formu oluşturur."""
    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        if not url or "docs.google.com/forms" not in url:
            return render_template_string(HTML_TEMPLATE, error="Geçerli bir Google Form URL'si girin.")
        
        form_data = analyze_google_form(url)
        if "error" in form_data:
            return render_template_string(HTML_TEMPLATE, error=form_data["error"])
        
        session['form_structure'] = form_data
        return render_template_string(HTML_TEMPLATE, form_data=form_data)
    
    return render_template_string(HTML_TEMPLATE)


@app.route('/submit', methods=['POST'])
def submit():
    """Klonlanan formu gönderince cevapları alır ve Excel dosyası oluşturur."""
    form_structure = session.get('form_structure')
    if not form_structure:
        return "Hata: Form yapısı bulunamadı. Lütfen formu ana sayfadan tekrar oluşturun.", 400

    user_answers = request.form
    results = []

    for question in form_structure['questions']:
        q_type = question.get('type')
        if q_type == 'Başlık':
            continue

        # NOT: Excel'e yazarken zengin metin istenmediği için burada HTML etiketleri temizlenir.
        q_text_plain = BeautifulSoup(question['text'], "html.parser").get_text(separator=" ", strip=True)
        answer_str = "Boş Bırakıldı"

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
        if not entry: continue

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
            answer_str = user_answers.get(entry, "Boş Bırakıldı")

        results.append({"Soru": q_text_plain, "Soru Tipi": q_type, "Cevap": answer_str})

    # Pandas DataFrame oluştur ve Excel'e yaz
    df = pd.DataFrame(results)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        sheet = 'Form Cevaplari'
        df.to_excel(writer, index=False, sheet_name=sheet)
        ws = writer.sheets[sheet]
        # Sütun genişliklerini otomatik ayarla
        for i, col in enumerate(df.columns):
            max_len = max([len(str(x)) for x in df[col].tolist()] + [len(col)])
            ws.column_dimensions[chr(65 + i)].width = min(max_len + 2, 70)
            
    output.seek(0)
    session.pop('form_structure', None) # Form yapısını session'dan temizle
    
    return send_file(output,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True,
                     download_name='form_cevaplari.xlsx')


# --- 6. UYGULAMANIN ÇALIŞTIRILMASI ---

if __name__ == '__main__':
    # Lokal geliştirme için. Production'da bu blok yerine Gunicorn gibi bir WSGI sunucusu kullanılır.
    app.run(host='0.0.0.0', port=5000, debug=True)
