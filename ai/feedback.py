import json
from datetime import datetime, timezone

from database.database import execute, query_all
from ai.ai_provider import get_ai


def build_feedback(attempt_id: int, marking: dict, transcripts: list[dict]) -> dict:
    ai = get_ai()
    if ai and ai.is_available():
        return build_feedback_with_ai(attempt_id, marking, transcripts, ai)
    
    # Fallback to rule-based feedback
    return build_feedback_rule_based(attempt_id, marking, transcripts)


def build_feedback_with_ai(attempt_id: int, marking: dict, transcripts: list[dict], ai) -> dict:
    """Use AI to generate contextual feedback based on actual student responses using 4XES2 markscheme."""
    student_responses = [t["text"] for t in transcripts if t.get("speaker") == "student"]
    all_responses_text = "\n\n".join([f"Response {i+1}: {r}" for i, r in enumerate(student_responses)])
    
    # Build comprehensive prompt with markscheme alignment
    prompt = f"""You are an expert IGCSE English as a Second Language examiner providing detailed, personalized feedback aligned with the Pearson 4XES2 mark scheme.

STUDENT'S RESPONSES:
{all_responses_text}

PERFORMANCE SCORES:
- Role play (Task 1): {marking.get('roleplay', {}).get('score', 0)}/10 marks
- Topic talk (Task 2): {marking.get('topic_talk', {}).get('score', 0)}/20 marks
- Picture conversation (Task 3): {marking.get('picture', {}).get('score', 0)}/20 marks
- Total score: {marking.get('total', 0)}/{marking.get('max_total', 50)} marks

4XES2 MARK SCHEME CONTEXT:
Task 1 Role Play marks for: clarity, appropriateness to context, unambiguous communication, pronunciation
Task 2/3 Communication marks for: detailed information, extended speech, spontaneous interaction, fluency, pronunciation
Task 2/3 Linguistic marks for: vocabulary range, sentence structures, accuracy

ANALYSIS INSTRUCTIONS:
1. Carefully analyze each response for:
   - Clarity and unambiguous communication (Task 1)
   - Extended sequences of speech and spontaneity (Task 2/3)
   - Vocabulary range and appropriateness (Task 2/3)
   - Sentence structure variety and accuracy (Task 2/3)
   - Pronunciation and intonation impact

2. Provide 3 SPECIFIC strengths:
   - What did the student do well according to 4XES2 criteria?
   - Reference specific examples from their responses
   - Highlight areas where they met the mark scheme descriptors

3. Provide 3 SPECIFIC weaknesses:
   - What needs improvement according to 4XES2 criteria?
   - Reference specific examples from their responses
   - Identify where they lost marks based on the descriptors
   - Note patterns that prevented higher bands

4. Provide 3 PRACTICAL recommendations:
   - How can they improve to reach higher bands?
   - Give specific, actionable advice aligned with 4XES2 descriptors
   - Suggest practice activities targeting weak areas
   - Reference their actual performance

IMPORTANT:
- Make feedback SPECIFIC to their actual responses, not generic
- Quote or reference specific things they said
- Be constructive and encouraging
- Focus on actionable improvements
- Align ALL feedback with Pearson 4XES2 assessment criteria
- Use terminology from the mark scheme (e.g., "extended sequences of speech", "spontaneous interaction", "wide range of vocabulary")

Return ONLY a JSON object with this format:
{{"strengths": ["specific strength 1", "specific strength 2", "specific strength 3"], "weaknesses": ["specific weakness 1", "specific weakness 2", "specific weakness 3"], "recommendations": ["specific recommendation 1", "specific recommendation 2", "specific recommendation 3"]}}"""

    try:
        ai_response = ai.generate_text(prompt, max_tokens=800, temperature=0.7, json_mode=True)
        # Parse JSON from AI response
        ai_response = ai_response.strip()
        if ai_response.startswith("```json"):
            ai_response = ai_response[7:]
        if ai_response.endswith("```"):
            ai_response = ai_response[:-3]
        result = json.loads(ai_response)
        
        strengths = result.get("strengths", [])
        weaknesses = result.get("weaknesses", [])
        recommendations = result.get("recommendations", [])
        lost = []
    except Exception as e:
        print(f"AI feedback generation failed: {e}")
        # Fallback to rule-based
        return build_feedback_rule_based(attempt_id, marking, transcripts)
    
    if not strengths:
        strengths.append("You completed the speaking tasks and produced rewardable communication.")

    student_bits = [t["text"] for t in transcripts if t.get("speaker") == "student"]
    evidence = " ".join(student_bits)[:500]
    comments = (
        f"{marking['disclaimer']}\n\n"
        f"Strongest area: {marking['strongest_area']}. "
        f"Weakest area: {marking['weakest_area']}.\n\n"
        f"Evidence from your responses: {evidence or 'No student speech was captured.'}"
    )
    payload = {
        "strengths": strengths,
        "weaknesses": weaknesses,
        "lost_marks": lost,
        "recommendations": recommendations,
        "examiner_comments": comments,
        "next_step": recommendations[0] if recommendations else "Repeat a full exam with a new card set.",
    }
    execute(
        """INSERT INTO feedback (attempt_id, strengths_json, weaknesses_json, lost_marks_json, recommendations_json, examiner_comments, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(attempt_id) DO UPDATE SET
             strengths_json=excluded.strengths_json,
             weaknesses_json=excluded.weaknesses_json,
             lost_marks_json=excluded.lost_marks_json,
             recommendations_json=excluded.recommendations_json,
             examiner_comments=excluded.examiner_comments""",
        (
            attempt_id,
            json.dumps(strengths),
            json.dumps(weaknesses),
            json.dumps(lost),
            json.dumps(recommendations),
            comments,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    return payload


def build_feedback_rule_based(attempt_id: int, marking: dict, transcripts: list[dict]) -> dict:
    strengths = []
    weaknesses = []
    lost = []
    recommendations = []

    # Analyze transcripts for specific patterns
    student_responses = [t["text"] for t in transcripts if t.get("speaker") == "student"]
    
    # Get stage information for context
    stages = [t.get("stage") for t in transcripts if t.get("speaker") == "student"]
    unique_stages = set(stages)
    
    # Dynamic analysis of actual responses
    total_words = sum(len(response.split()) for response in student_responses)
    avg_response_length = total_words / len(student_responses) if student_responses else 0
    
    # Analyze response patterns
    short_responses = sum(1 for response in student_responses if len(response.split()) < 6)
    complex_responses = sum(1 for response in student_responses if len(response.split()) > 20)
    
    # Vocabulary analysis
    all_words = " ".join(student_responses).lower().split()
    unique_words = set(all_words)
    vocabulary_richness = len(unique_words) / len(all_words) if all_words else 0
    
    # Grammar pattern analysis
    has_because = any("because" in response.lower() for response in student_responses)
    has_examples = any("for example" in response.lower() or "such as" in response.lower() for response in student_responses)
    has_connectors = any(word in response.lower() for response in student_responses for word in ["however", "although", "therefore", "moreover"])
    
    # Stage-specific feedback
    if "roleplay" in unique_stages:
        rp_responses = [t["text"] for t in transcripts if t.get("stage") == "roleplay" and t.get("speaker") == "student"]
        if rp_responses:
            rp_avg = sum(len(r.split()) for r in rp_responses) / len(rp_responses)
            if rp_avg < 5:
                weaknesses.append("Your role-play responses were too brief to fully address the prompts.")
                lost.append("Role play: single-word or very short answers cannot earn full marks.")
                recommendations.append("For each role-play bullet, give a complete sentence with at least 6-8 words.")
            elif rp_avg > 15:
                strengths.append("Your role-play responses were well-developed with appropriate detail.")
    
    if "topic_talk" in unique_stages:
        topic_responses = [t["text"] for t in transcripts if t.get("stage") == "topic_talk" and t.get("speaker") == "student"]
        if topic_responses:
            # Check for topic development
            topic_words = " ".join(topic_responses).lower()
            if any(word in topic_words for word in ["because", "since", "due to", "as"]):
                strengths.append("Your topic talk included good reasoning to support your opinions.")
            else:
                weaknesses.append("Your topic talk lacked clear reasoning or justification for your opinions.")
                recommendations.append("Always explain WHY you hold an opinion using 'because' or 'since'.")
            
            if any(word in topic_words for word in ["for example", "such as", "like", "for instance"]):
                strengths.append("You provided examples to make your topic talk more concrete.")
            else:
                weaknesses.append("Your topic talk would be stronger with specific examples.")
                recommendations.append("Add 'for example' followed by a specific instance to support your points.")
    
    if "picture" in unique_stages:
        pic_responses = [t["text"] for t in transcripts if t.get("stage") == "picture" and t.get("speaker") == "student"]
        if pic_responses:
            pic_words = " ".join(pic_responses).lower()
            if any(word in pic_words for word in ["in the photo", "i can see", "there is", "the picture shows"]):
                strengths.append("You provided clear description of what you can see in the photo.")
            if any(word in pic_words for word in ["might", "could", "would", "perhaps", "maybe"]):
                strengths.append("You used speculation appropriately in the picture discussion.")
            else:
                weaknesses.append("The picture discussion could include more speculation about what might be happening.")
                recommendations.append("Use 'might', 'could', or 'would' to speculate about the people and situation.")
    
    # General feedback based on actual content
    if vocabulary_richness > 0.6:
        strengths.append("You used a good range of vocabulary throughout your responses.")
    elif vocabulary_richness < 0.3:
        weaknesses.append("Your vocabulary was quite limited. Try to use more varied words and expressions.")
        recommendations.append("Practise using synonyms and more descriptive language.")
    
    if has_connectors:
        strengths.append("You used connecting words effectively to link your ideas.")
    else:
        weaknesses.append("Your responses felt like disconnected sentences.")
        recommendations.append("Use words like 'however', 'although', or 'therefore' to connect ideas.")
    
    if short_responses > len(student_responses) / 2:
        weaknesses.append("Many of your answers were too short to fully develop your ideas.")
        lost.append("Short answers cannot demonstrate your full speaking ability.")
        recommendations.append("Aim for at least 10-15 words per response to show development.")
    elif avg_response_length > 25:
        strengths.append("Your responses were well-developed with good length and detail.")
    
    # Score-based feedback
    if marking.get("roleplay", {}).get("score", 0) >= 8:
        strengths.append("Role play responses were generally clear and appropriate to the situation.")
    elif marking.get("roleplay", {}).get("score", 0) <= 5:
        weaknesses.append("Some role-play prompts were only partly communicated or too short.")
        lost.append("Role play: one-word or incomplete answers cannot reach 2 marks per prompt.")
        recommendations.append("Practise answering each role-play bullet with a short sentence, not a single word.")
    
    if marking.get("topic_talk", {}).get("communication_and_content", {}).get("score", 0) >= 7:
        strengths.append("Topic talk included relevant detail and some extended sequences of speech.")
    elif marking.get("topic_talk", {}).get("communication_and_content", {}).get("score", 0) <= 4:
        weaknesses.append("Topic talk ideas needed more development with reasons and examples.")
        recommendations.append("After an opinion, add because + an example before you stop speaking.")
    
    if marking.get("picture", {}).get("communication_and_content", {}).get("score", 0) >= 7:
        strengths.append("The picture discussion moved beyond description into opinion and explanation.")
    elif marking.get("picture", {}).get("communication_and_content", {}).get("score", 0) <= 4:
        weaknesses.append("Picture-based answers stayed close to description and needed more speculation and comparison.")
        recommendations.append("After describing the photo, add past experience, opinion, and a future prediction.")
    
    # Linguistic accuracy feedback
    topic_ling = marking.get("topic_talk", {}).get("linguistic_knowledge_and_accuracy", {}).get("score", 0)
    pic_ling = marking.get("picture", {}).get("linguistic_knowledge_and_accuracy", {}).get("score", 0)
    
    if topic_ling <= 4 or pic_ling <= 4:
        weaknesses.append("Linguistic accuracy dropped on longer answers.")
        lost.append("Linguistic knowledge and accuracy: frequent simple or inaccurate structures limited the band.")
        recommendations.append("Practise one accurate complex sentence with because / although / which.")
    
    if not strengths:
        strengths.append("You completed the speaking tasks and produced rewardable communication.")

    student_bits = [t["text"] for t in transcripts if t.get("speaker") == "student"]
    evidence = " ".join(student_bits)[:500]
    comments = (
        f"{marking['disclaimer']}\n\n"
        f"Strongest area: {marking['strongest_area']}. "
        f"Weakest area: {marking['weakest_area']}.\n\n"
        f"Evidence from your responses: {evidence or 'No student speech was captured.'}"
    )
    payload = {
        "strengths": strengths,
        "weaknesses": weaknesses,
        "lost_marks": lost,
        "recommendations": recommendations,
        "examiner_comments": comments,
        "next_step": recommendations[0] if recommendations else "Repeat a full exam with a new card set.",
    }
    execute(
        """INSERT INTO feedback (attempt_id, strengths_json, weaknesses_json, lost_marks_json, recommendations_json, examiner_comments, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(attempt_id) DO UPDATE SET
             strengths_json=excluded.strengths_json,
             weaknesses_json=excluded.weaknesses_json,
             lost_marks_json=excluded.lost_marks_json,
             recommendations_json=excluded.recommendations_json,
             examiner_comments=excluded.examiner_comments""",
        (
            attempt_id,
            json.dumps(strengths),
            json.dumps(weaknesses),
            json.dumps(lost),
            json.dumps(recommendations),
            comments,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    return payload


def recurring_themes(user_id: int) -> dict:
    rows = query_all(
        """SELECT f.weaknesses_json, f.recommendations_json, a.weakest_area
           FROM feedback f
           JOIN attempts a ON a.id = f.attempt_id
           WHERE a.user_id = ? AND a.status = 'completed'
           ORDER BY a.completed_at DESC LIMIT 12""",
        (user_id,),
    )
    counts = {}
    recs = []
    for row in rows:
        for item in json.loads(row["weaknesses_json"] or "[]"):
            counts[item] = counts.get(item, 0) + 1
        recs.extend(json.loads(row["recommendations_json"] or "[]"))
        if row["weakest_area"]:
            counts[row["weakest_area"]] = counts.get(row["weakest_area"], 0) + 1
    recurring = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "recurring_weaknesses": [k for k, v in recurring if v >= 2][:5],
        "recommended_practice": list(dict.fromkeys(recs))[:5],
    }