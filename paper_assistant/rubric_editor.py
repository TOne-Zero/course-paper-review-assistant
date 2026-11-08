"""本地教师演示模式：编辑、版本化保存、导入导出；不提供身份认证。"""

from dataclasses import replace
from uuid import uuid4

import streamlit as st

from paper_assistant.rubric_defaults import default_score_bands
from paper_assistant.rubrics import export_rubric, import_rubric, parse_rubric_config, rubric_to_dict, save_rubric
from paper_assistant.schemas import AssistantError, Rubric


def render_rubric_editor(rubric: Rubric) -> None:
    if not st.toggle("管理课程标准", key="teacher_demo"):
        return
    st.warning("此开关仅用于本机配置，不代表身份认证，也不限制其他本机使用者访问。没有正式账号系统。")
    st.caption("内置标准仅供参考，不是中国传媒大学或任何高校的官方标准。修改只有保存并选用后才参与分析。")
    with st.expander("编辑课程评分标准", expanded=True):
        source_key = (rubric.id, rubric.version)
        if st.session_state.get("rubric_draft_source") != source_key:
            st.session_state["rubric_draft_source"] = source_key
            st.session_state["rubric_draft"] = rubric_to_dict(rubric)
            st.session_state["rubric_draft_token"] = uuid4().hex
        draft = st.session_state["rubric_draft"]
        token = st.session_state["rubric_draft_token"]
        name = st.text_input("标准名称", value=draft["name"], key=f"rubric_name_{token}")
        description = st.text_area("标准说明", value=draft["description"], key=f"rubric_description_{token}")
        weight_note = st.text_area("权重与适用范围说明", value=draft["weight_note"], key=f"rubric_weights_{token}")
        st.caption(f"当前配置版本：{rubric.version}；配置格式版本：{rubric.schema_version}。保存后生成新的本地版本。")
        items = []
        for item in draft["dimensions"]:
            prefix = f"rubric_{token}_{item['id']}"
            with st.expander(f"维度：{item['name']}"):
                dim_name = st.text_input("维度名称", value=item["name"], key=prefix + "_name")
                score = st.number_input("维度满分", value=float(item["max_score"]), min_value=0.0, max_value=100.0, step=0.5, format="%.2f", key=prefix + "_score")
                goal = st.text_area("评价要求", value=item["description"], key=prefix + "_goal")
                checks = st.text_area("需要检查的内容（每行一项）", value="\n".join(item["checklist"]), key=prefix + "_checks")
                reference_lookup = {source["id"]: source for source in draft["references"]}
                reference_ids = st.multiselect(
                    "本维度参考来源（可取消关联）", options=list(reference_lookup),
                    default=item.get("reference_ids", []), key=prefix + "_references",
                    format_func=lambda value: value + " · " + reference_lookup[value]["citation"],
                ) if reference_lookup else []
                st.caption("分档按从低到高排列，完整覆盖 0–100%；下界包含、上界不包含，最后一档包含 100%。比例会按该维度满分换算。")
                bands = st.data_editor([
                    {"档位": band["label"], "最低百分比": band["min_ratio"] * 100,
                     "最高百分比": band["max_ratio"] * 100, "分档描述": band["description"]}
                    for band in item["score_bands"]
                ], num_rows="dynamic", hide_index=True, key=prefix + "_bands",
                    column_config={"最低百分比": st.column_config.NumberColumn(min_value=0, max_value=100),
                                   "最高百分比": st.column_config.NumberColumn(min_value=0, max_value=100)})
                remove = st.checkbox("保存时删除此维度", key=prefix + "_remove")
                if not remove:
                    try:
                        score_bands = [{"label": band["档位"], "min_ratio": float(band["最低百分比"]) / 100,
                                        "max_ratio": float(band["最高百分比"]) / 100, "description": band["分档描述"]}
                                       for band in bands]
                    except (ValueError, TypeError, KeyError):
                        score_bands = []
                    items.append(dict(item, name=dim_name, max_score=score, description=goal,
                                      checklist=[line.strip() for line in checks.splitlines() if line.strip()], score_bands=score_bands,
                                      reference_ids=reference_ids))
        total = round(sum(item["max_score"] for item in items), 2)
        st.text(f"草稿满分合计：{total:.2f} / 100")
        payload = dict(draft, name=name, description=description, weight_note=weight_note, dimensions=items, total_score=100)
        validation_error = None
        try:
            validated = parse_rubric_config(payload)
        except AssistantError as error:
            validation_error = str(error)
            st.error(validation_error)
        if st.button("添加维度", key="add_rubric_dimension"):
            # 保存当前控件编辑，再加入新维度；新维度默认分值需教师自行调整合计。
            draft.update(payload)
            draft["dimensions"].append({"id": "dim_" + uuid4().hex[:12], "name": "新增维度", "max_score": 10,
                                        "description": "请填写评价要求", "checklist": ["请填写需要检查的内容"],
                                        "score_bands": default_score_bands("本维度要求")})
            st.session_state["rubric_draft_token"] = uuid4().hex
            st.rerun()
        if st.button("保存并选用本地配置", key="save_rubric", disabled=validation_error is not None):
            try:
                local = rubric.id.startswith("local_")
                saved = save_rubric(replace(validated, id=rubric.id if local else "local_" + uuid4().hex),
                                    expected_version=rubric.version if local else None)
                st.session_state["pending_rubric_id"] = saved.id
                st.session_state["rubric_notice"] = f"配置已保存并选用，当前版本：{saved.version}。"
                st.rerun()
            except (AssistantError, OSError) as error:
                st.error(str(error) if isinstance(error, AssistantError) else "配置保存失败，请检查本地目录写入权限。")

    st.download_button("导出当前已选配置（JSON）", export_rubric(rubric), file_name=f"{rubric.id}.json", mime="application/json", key="export_rubric")
    imported = st.file_uploader("导入课程标准配置（JSON，最多 1 MB）", type=["json"],
                               key="import_rubric" + st.session_state.get("upload_generation", ""), max_upload_size=1)
    if st.button("导入并选用为新配置", key="apply_import_rubric", disabled=imported is None):
        try:
            loaded = import_rubric(imported.getvalue())
            saved = save_rubric(replace(loaded, id="local_" + uuid4().hex))
            st.session_state["pending_rubric_id"] = saved.id
            st.session_state["rubric_notice"] = f"配置已导入为新本地副本，当前版本：{saved.version}。"
            st.rerun()
        except (AssistantError, OSError) as error:
            st.error(str(error) if isinstance(error, AssistantError) else "导入后保存失败，请检查本地目录写入权限。")
