from database import db
from datetime import date, timedelta, timezone, datetime
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100),unique=True,nullable=False)
    name = db.Column(db.String(100),unique=False,nullable=False)
    password = db.Column(db.String(200),nullable=False)
    last_week_completed_tasks = db.Column(db.Integer, default=0)
    weekly_completed_tasks = db.Column(db.Integer, default=0)
    total_completed_tasks = db.Column(db.Integer, default=0)
    total_completed_projects = db.Column(db.Integer, default=0)
    average_completion_time = db.Column(db.Float, default=0.0)
    categories = db.Column(db.JSON)
    priorities = db.Column(db.JSON)
    last_login = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    streak = db.Column(db.Integer, default=0)
    tasks = db.relationship("Task", backref="user", lazy=True)
class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    title = db.Column(db.String(300),nullable=False)
    priority = db.Column(db.String(10),nullable=True)
    category = db.Column(db.String(50), default=None)
    due_date = db.Column(db.Date,nullable=True)
    @property
    def friendly_date(self):
        today = date.today()
        if self.due_date == today:
            return "Today"
        elif self.due_date == today + timedelta(days=1):
            return "Tomorrow"
        elif self.due_date == today - timedelta(days=1):
            return "Yesterday"
        return self.due_date.strftime("%d-%m-%Y")
    evaluate = db.Column(db.Boolean, default=False)
    subtasks = db.relationship('SubTask', backref='parent_task', lazy=True, cascade="all, delete-orphan")
    milestone_id = db.Column(db.Integer, db.ForeignKey("milestone.id"), nullable=True)
    pomodoro_id = db.Column(db.Integer, db.ForeignKey("pomodoro.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed = db.Column(db.Boolean, default=False)
class SubTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    parent_id=db.Column(db.Integer,db.ForeignKey('task.id'),nullable=False)
    title = db.Column(db.String(300),nullable=False)
    priority = db.Column(db.String(10),nullable=False)
    category = db.Column(db.String(50), default=None)
    due_date = db.Column(db.Date,nullable=True)
    @property
    def friendly_date(self):
        today = date.today()
        if self.due_date == today:
            return "Today"
        elif self.due_date == today + timedelta(days=1):
            return "Tomorrow"
        elif self.due_date == today - timedelta(days=1):
            return "Yesterday"
        return self.due_date.strftime("%d-%m-%Y")
class AISuggestions(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300),nullable=False)
    priority = db.Column(db.String(10),nullable=False)
    category = db.Column(db.String(50), default=None)
    due_date = db.Column(db.Date,nullable=True)
    user_id = db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
class CompletedTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300),nullable=False)
    user_id = db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    priority = db.Column(db.String(10),nullable=False)
    category = db.Column(db.String(50), default=None)
    completed_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    time_left = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    color = db.Column(db.String(20), default="#3B82F6")
    status = db.Column(db.String(20), default="active") # active, completed, maybe(archived)
    goal = db.Column(db.Text)
    target_date = db.Column(db.DateTime(timezone=True), nullable=True)
    progress = db.Column(db.Float, default=0)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    @property
    def target_day(self):
        today = date.today()
        if self.target_date  == today:
            return "Today"
        elif self.target_date == today + timedelta(days=1):
            return "Tomorrow"
        elif self.target_date == today - timedelta(days=1):
            return "Yesterday"
        return self.target_date.strftime("%d-%m-%Y")
    @property
    def updated_day(self):
        today = date.today()
        if self.updated_at  == today:
            return "Today"
        elif self.updated_at == today + timedelta(days=1):
            return "Tomorrow"
        elif self.updated_at == today - timedelta(days=1):
            return "Yesterday"
        return self.updated_at.strftime("%d-%m-%Y")
    milestones = db.relationship('Milestone', backref='project', lazy=True, cascade="all, delete-orphan")
    pmd_sessions = db.relationship('Pomodoro', backref='project', lazy=True, cascade="all, delete-orphan")
    completed_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
class Milestone(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    tasks = db.relationship("Task", backref="milestone", lazy=True, cascade="all, delete-orphan")
    progress = db.Column(db.Float, default=0)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    @property
    def updated_day(self):
        today = date.today()
        if self.updated_at  == today:
            return "Today"
        elif self.updated_at == today + timedelta(days=1):
            return "Tomorrow"
        elif self.updated_at == today - timedelta(days=1):
            return "Yesterday"
        return self.updated_at.strftime("%d-%m-%Y")
    status = db.Column(db.String(20), default="active")
class Pomodoro(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"),nullable=False)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=True)
    hours = db.Column(db.Integer, nullable=True)
    minutes = db.Column(db.Integer, nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"),nullable=True)
    tasks = db.relationship("Task", backref="pomodoro", lazy=True, cascade="all, delete-orphan")