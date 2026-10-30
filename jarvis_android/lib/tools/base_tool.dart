/// Base interface for Jarvis native mobile tools.
abstract class BaseTool {
  String get name;
  String get description;
  Map<String, dynamic> get parametersSchema;

  /// Returns Gemini Live JSON function declaration format
  Map<String, dynamic> toFunctionDeclaration() {
    return {
      'name': name,
      'description': description,
      'parameters': parametersSchema,
    };
  }

  /// Execute tool action with provided arguments
  Future<String> execute(Map<String, dynamic> args);
}
