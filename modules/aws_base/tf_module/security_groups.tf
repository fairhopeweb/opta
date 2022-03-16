resource "aws_security_group" "db" {
  name        = "opta-${var.layer_name}-db-sg"
  description = "For usage by databases to give access to resources in the vpc"
  vpc_id      = aws_vpc.vpc.id

  ingress {
    description = "postgres"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.vpc.cidr_block]
  }

  ingress {
    description = "mysql"
    from_port   = 3306
    to_port     = 3306
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.vpc.cidr_block]
  }
}

resource "aws_security_group" "elasticache" {
  name        = "opta-${var.layer_name}-elasticache-sg"
  description = "For usage by elasticache to give access to resources in the vpc"
  vpc_id      = aws_vpc.vpc.id

  # https://docs.aws.amazon.com/AmazonElastiCache/latest/mem-ug/elasticache-vpc-accessing.html
  ingress {
    description = "redis"
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.vpc.cidr_block]
  }

}

resource "aws_security_group" "documentdb" {
  name        = "opta-${var.layer_name}-documentdb-sg"
  description = "For usage by documentdb to give access to resources in the vpc"
  vpc_id      = aws_vpc.vpc.id

  # https://docs.aws.amazon.com/documentdb/latest/developerguide/db-cluster-create.html
  ingress {
    description = "documentdb"
    from_port   = 27017
    to_port     = 27017
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.vpc.cidr_block]
  }
}