# -*- coding: utf-8 -*-
"""
Google Form Klonlayıcı (Tam ve Güncel Versiyon - Güvenilir Görsel Alma)
Production (Railway / Render / Heroku) uyumlu.

ÖZELLİKLER:
- SECRET_KEY .env / ortam değişkeninden okunur.
- Google Form verisini çekip yeniden oluşturur ve cevapları Excel olarak indirir.
- Form/Bölüm başlıklarını ve soru açıklamalarını destekler.
- Kalın, italik, altı çizili, link ve liste gibi zengin metin formatlarını korur.
- Sorulara ve seçeneklere eklenen görselleri GÜVENİLİR bir şekilde destekler (HTML-öncelikli yeni yaklaşım).
- Seçili radyo düğmelerinin (çoktan seçmeli) seçimi tıklanarak kaldırılabilir.
- Tablo (grid), tarih, saat, derecelendirme gibi tüm temel soru tiplerini destekler.
"""

import os
import io
import json
import requests
import pandas as pd
from bs4 import BeautifulSoup
from flask import Flask, request, render_template_string, send_file, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-fallback-key")


def get_inner_html(element):
    """Bir BeautifulSoup elementinin iç HTML'ini string olarak döndürür."""
    if not element:
        return ""
    return "".join(map(str, element.contents)).strip()


# --- GÜNCELLENMİŞ VE İYİLEŞTİRİLMİŞ FONKSİYON ---
def analyze_google_form(url: str):
    """
    Google Form URL'sini parse ederek zengin metin ve görselleri içeren soru yapısını döndürür.
    YENİ YAKLAŞIM:
    1. Önce tüm HTML'i gezer ve her bir soru/bölümün görsel ve metinlerini bir haritaya kaydeder.
    2. Sonra JSON verisini işlerken bu haritayı kullanarak veriyi zenginleştirir.
    """
    try:
        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
            )
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        return {"error": f"URL okunamadı. Geçerli bir Google Form linki girin. Hata: {e}"}

    soup = BeautifulSoup(response.text, 'html.parser')
    
    # --- BÖLÜM 1: HTML'den Görsel ve Zengin Metinleri Çıkarıp Haritalama (İyileştirilmiş Mantık) ---
    html_data_map = {}
    # Her bir soru veya bölüm başlığı bu ana container içindedir
    all_items = soup.find_all('div', class_='Qr7Oae')

    for item_div in all_items:
        # data-item-id, bazen doğrudan Qr7Oae'nin içindeki bir div'de olabilir.
        element_with_id = item_div.find(attrs={'data-item-id': True})
        if not element_with_id or not element_with_id.has_attr('data-item-id'):
            continue
        
        item_id = element_with_id['data-item-id']

        # Zengin metinleri al (başlık ve açıklama)
        title_elem = item_div.find(class_='M7eMe')
        desc_elem = item_div.find(class_='gubaDc') or item_div.find(class_='spb5Rd')
        
        # [YENİ] Ana görseli bulmak için daha direkt bir yöntem
        # Ana görseller genellikle 'gCouxf' veya 'Y6Myld' gibi bir kapsayıcı içinde olur.
        main_img_container = item_div.find('div', class_='gCouxf')
        main_image_elem = main_img_container.find('img', class_='HxhGpf') if main_img_container else None
        main_image_url = main_image_elem['src'] if main_image_elem else None
        
        # Seçenek görsellerini metinleriyle eşleştir
        options_map = {}
        # Her bir seçenek (metin + görsel) bu kapsayıcı içindedir
        option_containers = item_div.select('.docssharedWizToggleLabeledContainer')
        for opt_container in option_containers:
            # Seçenek metnini bul
            text_span = opt_container.select_one('.aDTYNe')
            # Seçenek görselini bul
            img_tag = opt_container.find('img')
            
            if text_span:
                text = text_span.get_text(strip=True)
                img_src = img_tag['src'] if img_tag else None
                options_map[text] = img_src
        
        html_data_map[item_id] = {
            'text_html': get_inner_html(title_elem),
            'description_html': get_inner_html(desc_elem),
            'image_url': main_image_url,
            'options_map': options_map
        }

    # --- BÖLÜM 2: JSON Verisini İşle ve HTML Haritasıyla Zenginleştir ---
    form_data = {"questions": []}
    
    # Genel başlık ve açıklamayı al
    title_div = soup.find('div', class_='F9yp7e')
    form_data['title'] = get_inner_html(title_div) if title_div else "İsimsiz Form"
    desc_div = soup.find('div', class_='cBGGJ')
    form_data['description'] = get_inner_html(desc_div) if desc_div else ""
    
    script_tag = soup.find('script', string=lambda t: t and 'FB_PUBLIC_LOAD_DATA_' in t)
    if not script_tag:
        return {"error": "Form verisi (script) bulunamadı. URL'yi kontrol edin."}
    
    try:
        raw = script_tag.string.replace('var FB_PUBLIC_LOAD_DATA_ = ', '').rstrip(';')
        data = json.loads(raw)
        # Bazen form yapısı farklı bir indekste olabilir, kontrol ekleyelim
        if not data or len(data) < 2 or not data[1] or len(data[1]) < 2:
             return {"error": "Form yapısı (JSON) beklendiği gibi değil. Format değişmiş olabilir."}
        question_list = data[1][1]

        for q_data in question_list:
            try:
                # Soru ID'si ve Tipi
                item_id = str(q_data[0])
                q_type = q_data[3]

                # HTML haritasından zengin veriyi al, bulamazsan JSON'dan devam et
                scraped_data = html_data_map.get(item_id, {})
                
                question = {
                    'text': scraped_data.get('text_html') or q_data[1] or "", # Başlıksız sorular olabilir
                    'description': scraped_data.get('description_html') or (q_data[2] if len(q_data) > 2 else ""),
                    'image_url': scraped_data.get('image_url') # Direkt haritadan al
                }
                
                # Tip 6: Bölüm Başlığı / Sadece Resim. Bu bloklar sadece başlık, açıklama ve resim içerir.
                if q_type == 6:
                    question['type'] = 'Başlık'
                    form_data['questions'].append(question)
                    continue

                # Tip 7: Tablo (Grid) Soruları
                if q_type == 7:
                    rows_data = q_data[4]
                    if not isinstance(rows_data, list) or not rows_data: continue
                    first_row = rows_data[0]
                    # Onay Kutusu Tablosu mu, Çoktan Seçmeli Tablosu mu?
                    is_checkbox_grid = len(first_row) > 11 and first_row[11] and first_row[11][0]
                    question['type'] = 'Onay Kutusu Tablosu' if is_checkbox_grid else 'Çoktan Seçmeli Tablosu'
                    question['required'] = bool(first_row[2])
                    question['cols'] = [c[0] for c in first_row[1]]
                    question['rows'] = [{'text': r[3][0], 'entry_id': f"entry.{r[0]}"} for r in rows_data]
                    form_data['questions'].append(question)
                    continue
                
                # Diğer tüm soru tipleri için ortak bilgiler
                if not q_data[4]: continue # Soru bilgisi boşsa atla
                q_info = q_data[4][0]
                question['entry_id'] = f"entry.{q_info[0]}"
                question['required'] = bool(q_info[2])

                # Soru Tiplerine Göre Ayrıştırma
                if q_type == 0: question['type'] = 'Kısa Yanıt'
                elif q_type == 1: question['type'] = 'Paragraf'
                elif q_type in (2, 4):
                    question['type'] = 'Çoktan Seçmeli' if q_type == 2 else 'Onay Kutuları'
                    question['options'] = []
                    question['has_other'] = False
                    scraped_options = scraped_data.get('options_map', {})

                    for opt in q_info[1] or []:
                        text = opt[0]
                        if not text: continue
                        # "Diğer" seçeneğini kontrol et
                        if len(opt) > 4 and opt[4]:
                            question['has_other'] = True
                            continue
                        question['options'].append({
                            'text': text,
                            'image_url': scraped_options.get(text) # Haritadan ilgili resim URL'sini al
                        })
                elif q_type == 3:
                    question['type'] = 'Açılır Liste'
                    question['options'] = [o[0] for o in q_info[1] or [] if o[0]]
                elif q_type == 5:
                    question['type'] = 'Doğrusal Ölçek'
                    question['options'] = [o[0] for o in q_info[1]]
                    question['labels'] = q_info[3] if len(q_info) > 3 and q_info[3] else ["", ""]
                elif q_type == 18:
                    question['type'] = 'Derecelendirme' # Star rating
                    question['options'] = [str(o[0]) for o in q_info[1]]
                elif q_type == 9: question['type'] = 'Tarih'
                elif q_type == 10: question['type'] = 'Saat'
                else: continue # Bilinmeyen veya desteklenmeyen soru tipini atla
                
                form_data['questions'].append(question)

            except (IndexError, TypeError, KeyError) as e:
                # Bir soru bozuksa onu atla ve devam et
                print(f"Bir soru ayrıştırılırken hata oluştu (atlandı): {e} - Soru Verisi: {q_data}")
                continue
    
    except (json.JSONDecodeError, IndexError, TypeError) as e:
        return {"error": f"Form verileri ayrıştırılamadı (format değişmiş olabilir). Hata: {e}"}

    if not form_data['questions']:
        return {"error": "Formda analiz edilecek soru veya içerik bulunamadı."}
    return form_data


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="tr"><head><meta charset="UTF-8"><title>Google Form Klonlayıcı</title>
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<style>
body{font-family:Arial,sans-serif;background:#f4f7fa;margin:0;padding:2rem;display:flex;justify-content:center}
.container{max-width:760px;width:100%;background:#fff;padding:2rem 2.2rem;border-radius:12px;box-shadow:0 10px 25px rgba(0,0,0,.08)}
h1{text-align:center;margin:0 0 1rem}
.form-group{margin-bottom:1.6rem;padding:1.2rem;border:1px solid #dbe2e9;border-radius:8px;background:#fdfdff}
.question-label{display:block;font-weight:600;margin-bottom:.9rem}
.question-description{white-space:pre-wrap;color:#666;line-height:1.4;margin-top:-0.5rem;margin-bottom:0.9rem;font-size:0.9rem}
.question-description ul,.question-description ol{margin-top:0.5rem;padding-left:1.5rem;}
.required-star{color:#e74c3c;margin-left:4px}
input[type=text],input[type=email],textarea,select,input[type=date],input[type=time]{width:100%;padding:.8rem 1rem;border:1px solid #dbe2e9;border-radius:6px;box-sizing:border-box;font-size:1rem}
textarea{min-height:100px;resize:vertical}
input:focus,textarea:focus,select:focus{outline:none;border-color:#4a80ff;box-shadow:0 0 0 3px rgba(74,128,255,.2)}
.radio-group,.checkbox-group{display:flex;flex-direction:column;gap:.6rem}
.radio-group label,.checkbox-group label{display:flex;align-items:flex-start;gap:.8rem;cursor:pointer;padding:.6rem .7rem;border-radius:6px}
.radio-group label:hover,.checkbox-group label:hover{background:#f0f4ff}
input[type=radio],input[type=checkbox]{flex-shrink:0;margin-top:0.3rem;width:1.1rem;height:1.1rem;accent-color:#4a80ff}
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
.section-description{white-space:pre-wrap;color:#555;line-height:1.5;margin-top:0;font-size:0.95em}
.main-description{white-space:pre-wrap;color:#555;line-height:1.5;}
.main-description ul,.main-description ol{margin-top:0.5rem;padding-left:1.5rem;}
.form-image-container{text-align:center;margin-bottom:1rem;margin-top:1rem;}
.form-image-container img{max-width:100%;height:auto;max-height:450px;border-radius:8px;border:1px solid:#eee;}
.option-content{display:flex;flex-direction:column;align-items:flex-start;width:100%}
.option-image-container img{max-width:260px;width:100%;height:auto;display:block;margin-bottom:0.6rem;border-radius:6px;border:1px solid:#e0e0e0;}
.option-text{line-height:1.4}
</style></head>
<body><div class="container">
<h1>Google Form Klonlayıcı</h1>
<form method="post" action="/"><div class="form-group" style="padding:0.8rem;">
<input type="text" name="url" placeholder="https://docs.google.com/forms/d/e/..." required>
<button type="submit" class="btn" style="margin-top:.8rem;">Formu Oluştur</button>
</div></form>
{% if error %}<div class="error-message">{{ error }}</div>{% endif %}
{% if form_data %}
<h2 style="text-align:center;margin-top:1.5rem;">{{ form_data.title | safe }}</h2>
{% if form_data.description %}<div class="main-description">{{ form_data.description | safe }}</div>{% endif %}
<form method="post" action="/submit">
{% for q in form_data.questions %}
    {% if q.type == 'Başlık' %}
    <div class="title-description-block">
        {% if q.text %}<div class="section-title">{{ q.text | safe }}</div>{% endif %}
        {% if q.description %}<div class="section-description">{{ q.description | safe }}</div>{% endif %}
        {% if q.image_url %}<div class="form-image-container"><img src="{{ q.image_url }}" alt="Başlık Görseli"></div>{% endif %}
    </div>
    {% else %}
    <div class="form-group">
        <div class="question-label">{{ q.text | safe }} {% if q.required %}<span class="required-star">*</span>{% endif %}</div>
        {% if q.description %}<div class="question-description">{{ q.description | safe }}</div>{% endif %}
        {% if q.image_url %}<div class="form-image-container"><img src="{{ q.image_url }}" alt="Soru Görseli"></div>{% endif %}

        {% if q.type == 'Kısa Yanıt' %} <input type="text" name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
        {% elif q.type == 'Paragraf' %} <textarea name="{{ q.entry_id }}" {% if q.required %}required{% endif %}></textarea>
        {% elif q.type == 'Çoktan Seçmeli' %} <div class="radio-group">
            {% for opt in q.options %}
            <label>
                <input type="radio" name="{{ q.entry_id }}" value="{{ opt.text }}" {% if q.required %}required{% endif %}>
                <div class="option-content">
                    {% if opt.image_url %}<div class="option-image-container"><img src="{{ opt.image_url }}" alt="{{ opt.text }}"></div>{% endif %}
                    <span class="option-text">{{ opt.text }}</span>
                </div>
            </label>
            {% endfor %}
            {% if q.has_other %}<label class="other-option-label"><input type="radio" name="{{ q.entry_id }}" value="__other_option__"><span>Diğer:</span><input type="text" class="other-option-input" name="{{ q.entry_id }}.other_option_response"></label>{% endif %}
        </div>
        {% elif q.type == 'Onay Kutuları' %} <div class="checkbox-group">
            {% for opt in q.options %}
            <label>
                <input type="checkbox" name="{{ q.entry_id }}" value="{{ opt.text }}">
                <div class="option-content">
                    {% if opt.image_url %}<div class="option-image-container"><img src="{{ opt.image_url }}" alt="{{ opt.text }}"></div>{% endif %}
                    <span class="option-text">{{ opt.text }}</span>
                </div>
            </label>
            {% endfor %}
            {% if q.has_other %}<label class="other-option-label"><input type="checkbox" name="{{ q.entry_id }}" value="__other_option__"><span>Diğer:</span><input type="text" class="other-option-input" name="{{ q.entry_id }}.other_option_response"></label>{% endif %}
        </div>
        {% elif q.type == 'Açılır Liste' %} <select name="{{ q.entry_id }}" {% if q.required %}required{% endif %}><option value="" disabled selected>Seçin...</option>{% for opt in q.options %}<option value="{{ opt }}">{{ opt }}</option>{% endfor %}</select>
        {% elif q.type == 'Doğrusal Ölçek' %} <div class="radio-group" style="flex-direction:row;justify-content:space-around;align-items:center;"><span>{{ q.labels[0] }}</span>{% for opt in q.options %}<label style="flex-direction:column;align-items:center;"><span>{{ opt }}</span><input type="radio" name="{{ q.entry_id }}" value="{{ opt }}" {% if q.required %}required{% endif %}></label>{% endfor %}<span>{{ q.labels[1] }}</span></div>
        {% elif q.type == 'Derecelendirme' %} <div class="rating-group">{% for opt in q.options | reverse %}<input type="radio" id="star{{ opt }}-{{ q.entry_id }}" name="{{ q.entry_id }}" value="{{ opt }}" {% if q.required %}required{% endif %}><label for="star{{ opt }}-{{ q.entry_id }}">★</label>{% endfor %}</div>
        {% elif q.type == 'Tarih' %} <input type="date" name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
        {% elif q.type == 'Saat' %} <input type="time" name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
        {% elif q.type in ['Çoktan Seçmeli Tablosu','Onay Kutusu Tablosu'] %}
        <table class="grid-table"><thead><tr><th></th>{% for col in q.cols %}<th>{{ col }}</th>{% endfor %}</tr></thead><tbody>{% for row in q.rows %}<tr><td>{{ row.text }}</td>{% for col in q.cols %}<td><input type="{{ 'checkbox' if 'Onay' in q.type else 'radio' }}" name="{{ row.entry_id }}" value="{{ col }}" {% if q.required %}required{% endif %}></td>{% endfor %}</tr>{% endfor %}</tbody></table>
        {% endif %}
    </div>
    {% endif %}
{% endfor %}
<button type="submit" class="btn">Gönder ve Excel Olarak İndir</button>
</form>
{% endif %}
</div>

<!-- Seçili radyo düğmesine tıklanınca seçimi kaldırmak için JS -->
<script>
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('input[type=radio]').forEach(radio => {
    radio.addEventListener('mousedown', function() {
      this.wasChecked = this.checked;
    });
    radio.addEventListener('click', function() {
      if (this.wasChecked) {
        this.checked = false;
        this.wasChecked = false;
      }
    });
  });
});
</script>

</body></html>
"""


@app.route('/', methods=['GET', 'POST'])
def index():
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
            if final:
                answer_str = ', '.join(final)
        elif q_type == 'Çoktan Seçmeli':
            ans = user_answers.get(entry)
            if ans == "__other_option__":
                other_txt = user_answers.get(f"{entry}.other_option_response", "").strip()
                answer_str = f"Diğer: {other_txt}" if other_txt else "Diğer (belirtilmemiş)"
            elif ans:
                answer_str = ans
        else:
            answer_str = user_answers.get(entry, "Boş Bırakıldı")

        if answer_str: # Sadece dolu cevapları eklemek için
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
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='form_cevaplari.xlsx'
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
