
class PipelineError(Exception):
    """base class for the errors the pipeline raises itself"""

class RetryableError(PipelineError):
    """a failure that can succeed on another try. timeout, dropped connection"""

class UnexpectedContentType(PipelineError):
    """a sprite url answered with something that is not the png or gif its name says"""

class RateLimited(PipelineError):
    """the server wants this ip to slow down, retrying right away only makes it worse"""