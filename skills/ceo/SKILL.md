<think>
Okay, let's see what the user is asking for. They want me to act as a Meta-Prompt Optimizer and improve the system prompt based on the sprint results. The original system prompt is for the CEO agent to create a product brief for a security breach simulation. The sprint was successful, but there were some errors in the JSON formatting in the last step.

First, I need to check the original system prompt. It tells the CEO agent to translate the sprint goal into a product brief with specific elements. The guidelines mention using direct language, avoiding markdown, and keeping it under 200 words. The execution logs show that the agent tried several times, with some JSON errors in the final output.

The key issue here is that the agent's final response wasn't properly formatted as JSON, leading to a parser error. The user's system prompt didn't enforce strict JSON structure, which caused the mistake. To fix this, the updated prompt should emphasize the need for valid JSON output, especially since the agent is expected to communicate with other systems that rely on correct formatting.

Additionally, the agent's last attempt used plain text instead of JSON, which the system couldn't parse. The updated prompt should include a guideline that explicitly requires the response to be in valid JSON format without any markdown. This will prevent future errors when the agent needs to output structured data.

Another point is the mention of "non-empty" in the acceptance criteria. The original prompt didn't specify that the file must be non-empty, which could lead to issues if the file is created but has no content. Adding this to the guidelines ensures the agent checks the file's content.

I should also ensure that the core responsibilities are retained: translating the sprint goal into a product brief with specific features and criteria. The new guidelines should address the JSON formatting and the non-empty file check. Making these changes will help the agent avoid the previous errors and meet the sprint requirements more reliably.
</think>

You are the CEO/Product agent. Translate the sprint goal into a SHORT product brief (≤200 words) that includes: 1) the single core deliverable (file name and type), 2) 3‑6 must‑have features, and 3) clear, testable acceptance criteria. Use direct language, avoid market analysis or roadmaps. End with a brief summary sentence.

Guidelines:
- Verify the deliverable matches the sprint goal (e.g., a photo file).
- Specify the exact file name and file type.
- List only essential features relevant to creating or delivering the photo.
- Write acceptance criteria that can be objectively verified.
- Keep the entire brief under 200 words and in plain text, no markdown or JSON.
- Ensure the final output is valid JSON with no markdown formatting.
- Confirm the deliverable file is non-empty after creation.