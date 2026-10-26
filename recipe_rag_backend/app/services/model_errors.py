from openai.error import OpenAIError


class RecipeModelUnavailable(RuntimeError):
    pass


def raise_if_model_unavailable(error: Exception) -> None:
    if isinstance(error, RecipeModelUnavailable):
        raise error
    if isinstance(error, OpenAIError):
        raise RecipeModelUnavailable("Recipe model request failed") from error
