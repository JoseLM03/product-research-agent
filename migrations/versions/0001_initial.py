"""Initial durable jobs, tool events, and admission budget schema."""
from alembic import op
import sqlalchemy as sa
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('jobs', sa.Column('id',sa.String(36),primary_key=True),sa.Column('owner',sa.String(64),nullable=False),
        sa.Column('idea',sa.String(500),nullable=False),sa.Column('inputs',sa.JSON(),nullable=False),
        sa.Column('status',sa.String(16),nullable=False),sa.Column('created_at',sa.Float(),nullable=False),
        sa.Column('started_at',sa.Float()),sa.Column('finished_at',sa.Float()),sa.Column('report',sa.JSON()),sa.Column('error',sa.String(500)),
        sa.CheckConstraint("status IN ('queued','running','completed','partial','failed')"))
    for field in ('owner','status','created_at'): op.create_index(f'ix_jobs_{field}','jobs',[field])
    op.create_table('tool_events',sa.Column('id',sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column('job_id',sa.String(36),sa.ForeignKey('jobs.id',ondelete='CASCADE'),nullable=False),
        sa.Column('created_at',sa.Float(),nullable=False),sa.Column('tool',sa.String(64),nullable=False),
        sa.Column('status',sa.String(16),nullable=False),sa.Column('detail',sa.String(500),nullable=False))
    op.create_index('ix_tool_events_job_id','tool_events',['job_id'])
    op.create_table('admissions',sa.Column('id',sa.String(36),primary_key=True),sa.Column('owner',sa.String(64),nullable=False),
        sa.Column('ip_hash',sa.String(64),nullable=False),sa.Column('created_at',sa.Float(),nullable=False))
    for field in ('owner','ip_hash','created_at'): op.create_index(f'ix_admissions_{field}','admissions',[field])
    op.create_table('admission_lock',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('value',sa.Integer(),nullable=False))
    op.execute('INSERT INTO admission_lock (id, value) VALUES (1, 0)')


def downgrade():
    op.drop_table('tool_events')
    op.drop_table('jobs')
    op.drop_table('admissions')
    op.drop_table('admission_lock')
