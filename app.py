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
        answer_str = user_answers.get(entry, "Boş Bırakıldı")

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
