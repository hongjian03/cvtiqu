import streamlit as st
import json
import os
import asyncio
from pathlib import Path
from processor import SimpleProcessor
from llm_processor import LLMProcessor
import tempfile
from qs_usnews_school_dict import qs_school_ranking, usnews_school_ranking
from test_llm import calculate_student_tags, enrich_school_rankings

# 设置页面配置
st.set_page_config(
    page_title="简历和Offer分析工具",
    page_icon="📄",
    layout="wide"
)

# 初始化会话状态
if 'resume_prompt' not in st.session_state:
    llm_processor = LLMProcessor()
    st.session_state.resume_prompt = llm_processor._get_resume_prompt("")
    st.session_state.offer_prompt = llm_processor._get_offer_prompt("")

# 初始化处理器
@st.cache_resource
def get_processor():
    return SimpleProcessor()

@st.cache_resource
def get_llm_processor():
    llm_processor = LLMProcessor(
        api_key=st.secrets["OPENAI_API_KEY"],
        api_base=st.secrets["OPENAI_API_BASE"],
        model_name=st.secrets["OPENAI_MODEL"]
    )
    # 使用会话状态中的提示词
    llm_processor.resume_prompt = st.session_state.resume_prompt
    llm_processor.offer_prompt = st.session_state.offer_prompt
    return llm_processor

# 主页面
def main_page():
    langsmith_api_key = st.secrets["LANGCHAIN_API_KEY"]
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = "简历和Offer分析工具"
    st.title("📄 简历和Offer分析工具")
    
    # 创建两列布局
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("上传简历文件")
        resume_file = st.file_uploader("选择PDF格式的简历文件", type=["pdf"], key="resume")
        
    with col2:
        st.subheader("上传Offer文件")
        offer_files = st.file_uploader("选择PDF格式的Offer文件", type=["pdf"], key="offer", accept_multiple_files=True)
    
    # 分析按钮
    if st.button("开始分析", type="primary"):
        if resume_file is None and not offer_files:
            st.error("请至少上传一个文件进行分析")
            return
        st.write(f"简历提示词：{st.session_state.resume_prompt}")
        st.write(f"Offer提示词：{st.session_state.offer_prompt}")
        with st.spinner("正在分析中..."):
            processor = get_processor()
            llm_processor = get_llm_processor()
            
            # 创建临时文件
            with tempfile.TemporaryDirectory() as temp_dir:
                results = {}
                
                # 处理简历
                if resume_file is not None:
                    resume_path = os.path.join(temp_dir, "resume.pdf")
                    with open(resume_path, "wb") as f:
                        f.write(resume_file.getvalue())
                    
                    # 提取文本
                    resume_result = processor.process_resume(resume_path)
                    if resume_result["success"]:
                        # 使用LLM分析
                        resume_analysis = llm_processor.analyze_resume(resume_result["content"])
                        results["resume_analysis"] = resume_analysis
                    else:
                        st.error(f"简历分析失败: {resume_result['error']}")
                
                # 处理Offer
                if offer_files:
                    offer_paths = []
                    for i, offer_file in enumerate(offer_files):
                        offer_path = os.path.join(temp_dir, f"offer_{i}.pdf")
                        with open(offer_path, "wb") as f:
                            f.write(offer_file.getvalue())
                        offer_paths.append(offer_path)
                    
                    # 提取文本 - 使用文件路径列表调用process_offer
                    offer_results = processor.process_offer(offer_paths)
                    offer_texts = []
                    
                    for offer_result in offer_results:
                        if offer_result["success"]:
                            offer_texts.append(offer_result["content"])
                        else:
                            st.error(f"Offer分析失败: {offer_result['error']}")
                    
                    if offer_texts:
                        # 使用LLM分析
                        api_results = asyncio.run(llm_processor.process_documents(
                            resume_text=resume_result["content"] if resume_file else "",
                            offer_texts=offer_texts
                        ))
                        
                        # 确保offer_analyses是一个列表
                        if isinstance(api_results, dict):
                            offer_analyses = api_results.get("offer_analyses", [])
                        else:
                            offer_analyses = []
                        
                        # 处理可能的格式不一致情况
                        processed_offer_analyses = []
                        for offer in offer_analyses:
                            # 检查offer是否为字典且包含admissions字段
                            if isinstance(offer, dict) and "admissions" in offer:
                                processed_offer_analyses.append(offer)
                            # 如果offer是字符串，尝试解析为JSON
                            elif isinstance(offer, str):
                                try:
                                    offer_dict = json.loads(offer)
                                    processed_offer_analyses.append(offer_dict)
                                except:
                                    # 如果无法解析为JSON，包装为统一格式
                                    processed_offer_analyses.append({"admissions": []})
                            else:
                                # 确保每个offer至少有一个空的admissions列表
                                processed_offer_analyses.append({"admissions": []})
                        
                        results["offer_analyses"] = processed_offer_analyses
                
                # 计算标签和丰富学校排名
                if results:
                    # 丰富学校排名
                    try:
                        enrich_school_rankings(results)
                    except Exception as e:
                        st.warning(f"丰富学校排名时出错: {str(e)}")
                        
                    # 计算标签
                    try:
                        tags = calculate_student_tags(results)
                        if tags:
                            results["tags"] = tags
                    except Exception as e:
                        st.warning(f"计算标签时出错: {str(e)}")
                    # 显示结果
                    st.subheader("分析结果")
                    st.json(results)
                    
                    # 保存结果到文件
                    with open("combined_analysis.json", "w", encoding="utf-8") as f:
                        json.dump(results, f, ensure_ascii=False, indent=2)
                    st.success("分析结果已保存到 combined_analysis.json")

# 提示词管理页面
def prompts_page():
    st.title("🔧 提示词管理")
    
    # 简历分析提示词
    st.subheader("简历分析提示词")
    resume_prompt = st.text_area(
        "简历分析提示词",
        value=st.session_state.resume_prompt,
        height=200,
        key="resume_prompt_input"
    )
    
    # Offer分析提示词
    st.subheader("Offer分析提示词")
    offer_prompt = st.text_area(
        "Offer分析提示词",
        value=st.session_state.offer_prompt,
        height=200,
        key="offer_prompt_input"
    )
    
    # 更新按钮
    if st.button("更新提示词", type="primary"):
        # 更新会话状态中的提示词
        st.session_state.resume_prompt = resume_prompt
        st.session_state.offer_prompt = offer_prompt
        st.success("提示词已更新！")
        
        # 重新初始化LLM处理器以应用新的提示词
        st.cache_resource.clear()
        get_llm_processor()

# 主程序
def main():
    # 创建标签页
    tab1, tab2 = st.tabs(["📄 文件分析", "🔧 提示词管理"])
    
    with tab1:
        main_page()
    
    with tab2:
        prompts_page()

if __name__ == "__main__":
    main()
