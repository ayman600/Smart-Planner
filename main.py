from flask import Flask, render_template,request,redirect,url_for,session,flash,make_response
from flask_mail import Mail, Message
from premailer import transform
from flask_apscheduler import APScheduler
from datetime import date,datetime,timezone,timedelta
from functools import wraps
from database import db
from sqlalchemy import case 
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from ai_models import AIModels
from email_validator import validate_email,EmailNotValidError
import os
app = Flask(__name__)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
load_dotenv()
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = os.environ.get("address_email")
app.config['MAIL_PASSWORD'] = os.environ.get("password_email")
app.secret_key = os.environ.get("SECRET_KEY")
mail=Mail()
mail.init_app(app)
tasks=None
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///horizons.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)
from models import CompletedTask, User, Task, AISuggestions, SubTask, Project, Milestone
with app.app_context():
    db.create_all()
ai_models=AIModels()
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            if request.headers.get("HX-Request"):
                response=make_response("",200)
                response.headers["HX-Redirect"] = url_for('log_in')
                return response
            return redirect(url_for("log_in"))
        return f(*args, **kwargs)
    return decorated_function
def update_streak():
    user = User.query.filter_by(id=session['user_id'])
    try:
        now = datetime.now(timezone.utc)
        today = now.date()
        if not user.last_login:
            user.streak = 1
            user.last_login = now
            session["streak"]=user.streak
            db.session.commit()
            return
        else:
            last_login_date = user.last_login.replace(tzinfo=timezone.utc).date()
            difference = (today-last_login_date).days
            if difference==0:
                pass
            elif difference==1:
                user.streak+=1
                user.last_login = now
            else:
                user.streak = 1
                user.last_login = now
        session['streak']=user.streak
        db.session.commit()
    except:
        db.session.rollback()

def purge_expired_tasks():
    expired_time=datetime.now(timezone.utc) - timedelta(hours=12)
    expired_completed_tasks=CompletedTask.query.filter(CompletedTask.user_id==session['user_id'],CompletedTask.completed_at<=expired_time)
    expired_completed_tasks.delete()
    db.session.commit()

def check_strong_password(password):
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if not any(char.isupper() for char in password):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not any(char.islower() for char in password):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not any(char.isdigit() for char in password):
        raise ValueError("Password must contain at least one number.")
    if not any(char in '@#$%!*&' for char in password):
        raise ValueError("Password must contain at least one special character (@, #, $, %, !, *, &).")
        
    return True

def insights(user):
    try:
        week_completed_tasks = user.weekly_completed_tasks or 0 #! return type 'int'
        total_completed_tasks = user.total_completed_tasks or 0 #! return type 'int' 
        last_week_completed_tasks = user.last_week_completed_tasks or 0
        weekly_change=['no change from last week',0]
        if last_week_completed_tasks == 0:
            if week_completed_tasks > 0:
                weekly_change[0] =  f"{week_completed_tasks} new tasks completed!"
                weekly_change[1] = 1
            else:
                weekly_change[0] = 'no data from last week'
        else:
            change_percent =  ((week_completed_tasks - last_week_completed_tasks) / last_week_completed_tasks) * 100        
            if change_percent > 0:
                weekly_change[0] =  f"{change_percent:.1f}% from last week"
                weekly_change[1] = 1

            elif change_percent < 0:
                weekly_change[0] =  f"{abs(change_percent):.1f}% from last week"
                weekly_change[1] = 0
            else:
                weekly_change[0] = 'no change from last week'
                weekly_change[1] = 0
        average_completion_time = user.average_completion_time or 0.0 #! return type 'float' or 'str'
        total_minutes = round(average_completion_time*60)
        if total_minutes<1:
            average_completion_time = 'In record time!'
        elif total_minutes<60:
            average_completion_time = f"{total_minutes} mins"
        else:
            hours = total_minutes // 60
            minutes = total_minutes % 60
            if minutes == 0:
                average_completion_time = f"{hours}h"
            else:
                average_completion_time = f"{hours}h {minutes}m"
        categories=user.categories if user.categories else {}
        if categories:
            top_category = max(categories, key = categories.get) #! return type 'str' or None
        else:
            top_category = None
        count_priority_tasks = user.priorities or {'high': 0, 'medium': 0, 'low': 0} #! return type {'high':num,'medium':num,'low':num}
        if any(count_priority_tasks):
            top_priority = max(count_priority_tasks, key=count_priority_tasks.get)
        else:
            top_priority = None
        projects = []
        active_projects = 0
        all_projects = Project.query.filter_by(user_id=session['user_id']).all()
        for i in all_projects:
            current_project = {'title': i.title, 'progress': f"{i.progress}%", 'target_date': i.target_date, 'last_update': i.updated_at}
            projects.append(current_project)
            if i.status != 'completed':
                active_projects += 1
        completed_projects = user.total_completed_projects or 0
    except Exception as e:
        print(f"Error: {e}")
        
    return {"name":user.name,"Total completed tasks":total_completed_tasks,"Total completed tasks this week":week_completed_tasks, 'weekly change': weekly_change,"Average completion time in hours":average_completion_time,"top category":top_category,"Count completed tasks by priority":count_priority_tasks,'top priority':top_priority, 'projects':projects, 'total completed projects': completed_projects, 'total active projects': active_projects}

scheduler = APScheduler()
@scheduler.task('cron', id='weekly_insights_reset', day_of_week='sun', hour=23, minute=59)
def weekly_static():
    with app.app_context():
        users=User.query.all()
        for user in users:
            try:
                statics=insights(user)
                ai_email=ai_models.static_generator_message(statics)
                email= render_template('weekly_static_table.html', static=statics, ai_output=ai_email)
                message = Message(subject='Your Smart Planner weekly summary', sender="ayman.laa09@gmail.com",recipients=[user.username])
                email=transform(email)
                message.html = email
                mail.send(message)
                user.last_week_completed_tasks = user.weekly_completed_tasks
                user.weekly_completed_tasks = 0
                user.priorities = {'high':0,'medium':0,'low':0}
                user.categories = ''
                user.average_completion_time = 0.0
                db.session.commit()
            except:
                db.session.rollback()
scheduler.init_app(app)
scheduler.start()

#!#! change demo url
def greating_email(user_email,name):
    try:
        greating_email=f'''<p>Hi {name},</p>
        <p>Welcome to <strong>Smart Planner</strong>! 🚀 Your new personal command center for organizing your tasks and staying productive.<p>
        <p>Your account is officially ready✅. Here is what you can do <strong>right out of the gate</strong>:<p>
        <ul>
            <li>📝 <strong>Organize Your Tasks: Add your tasks, tag their priority levels, and categorize them to keep your workflow clean.</strong></li>
            <li>📊 <strong>Track Your Progress: Every task you check off feeds into your dashboard metrics.</strong></li>
            <li>📈 <strong>Unlock Weekly Insights: Our background system calculates your stats every single week, showing you your average completion times and top categories.</strong></li>
            <li>🤖 <strong>Enjoy you journey powered by AI.</strong></li>
        </ul>
        <p>👉 The board is clear and ready for your first task.<strong><a href="http://smartplanner.ayman.hackclub.app/dashboard" style="color: #007bff; font-weight: bold; text-decoration: underline;">Log in and start achieving your goals</a></strong></p>
        <p>Happy organizing,<br>
        <strong>The Smart Planner Team.</strong>🌟</p>
        '''
        message = Message(subject='WELCOME TO Smart Planner!',sender='ayman.laa09@gmail.com',recipients=[user_email])
        message.html = greating_email
        mail.send(message)
    except Exception as e:
        print(F"Error: {e}")


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html',title='404'), 404

@app.route('/')
@app.route('/home')
def home():
    return render_template('home.html',title='Home')


@app.route('/sign_up',methods=['POST','GET'])
def sign_up():
    if "user_id" in session:
         return redirect(url_for("dashboard"))
    error=None
    if request.method=='POST':
        try:
            username = request.form.get("username")
            password = request.form.get("password")
            verify = request.form.get("verifypassword")
            email = validate_email(username, check_deliverability=True)
            valid_email = email.normalized
            check_strong_password(password)
            if password != verify:
                raise ValueError("Password do not match")
            existing_user=User.query.filter_by(username=valid_email).first()
            if existing_user:
                raise ValueError('An account with this email address already exists.')
            new_user = User(username=valid_email,name='',password=generate_password_hash(password),last_login=datetime.now(timezone.utc))
            db.session.add(new_user)
            db.session.commit()
            session["user_id"]=new_user.id
            session["username"]=new_user.username
            purge_expired_tasks()
            return redirect(url_for('user_name'))
        except (ValueError,EmailNotValidError) as e:
            error=str(e)
    return render_template('sign_up.html',title='Sign up',error=error)

@app.route('/user_name',methods=['POST','GET'])
def user_name():
    if request.method=='POST':
        name=request.form.get("name")
        user = User.query.filter_by(id=session["user_id"]).first_or_404()
        user.name=name
        greating_email(user.username,name)
        user.streak = 1
        db.session.commit()
        session['name'] = name
        session['streak'] = 1
        return redirect(url_for('dashboard'))
    return render_template("user's_name.html")


@app.route('/log_in',methods=['POST','GET'])
def log_in():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    error=None
    if request.method=='POST':
        username = request.form.get("username")
        password = request.form.get("password")
        try:
            user = User.query.filter_by(username=username).first()
            if user is None or not check_password_hash(user.password, password):
                raise ValueError("Invalid Email or Password")
            session["user_id"] = user.id
            session["username"] = user.username
            session["name"] = user.name
            session['streak'] = user.streak
            purge_expired_tasks()
            return redirect(url_for("dashboard"))
        except ValueError as e:
            error=str(e)
    return render_template('log_in.html',title='Log in',error=error)


@app.route("/dashboard")
@login_required
def dashboard():
    update_streak()
    sort = request.args.get("sort", "date")
    user = User.query.filter_by(id=session["user_id"]).first()
    if user is None:
        session.clear()
        return redirect(url_for("log_in"))
    name=session['name']
    query = Task.query.filter_by(user_id=session["user_id"], milestone_id=None)
    if sort == "priority":
        query = query.order_by(case((Task.priority == "High", 1),(Task.priority == "Medium", 2),(Task.priority == "Low", 3),))
    elif sort == "name":
        query = query.order_by(Task.title)
    else:
        query = query.order_by(Task.due_date)
    tasks = query.all()
    return render_template("dashboard.html",title="Dashboard",tasks=tasks,status="dashboard",name=name,streak=session['streak'])
@app.route("/task/new", methods=['GET','POST'])
@login_required
def add_task():
    update_streak()
    name=session['name']
    if request.method == "POST":
        try:
            task = request.form["task"]
            priority = request.form["priority"]
            due_date = request.form["due_date"]
            category= request.form["category"]
            user_id=session["user_id"]
            evaluate=ai_models.evaluate_task(task)
            if not category:
                category=ai_models.determinate_category(task)
                if category=='None':
                    category=None
            if evaluate=="yes":
                evaluate=True
            else :
                evaluate=False
            if due_date:
                due_date=date.fromisoformat(due_date)
            else:
                due_date=None
            new_task = Task(title=task,priority=priority,due_date=due_date,user_id=user_id,category=category,evaluate=evaluate,created_at=datetime.now(timezone.utc))
            db.session.add(new_task)
            db.session.commit()
            flash("Task added successfully!", "success")
        except :
            flash(f"Something went wrong", "error")
            db.session.rollback()
        return redirect(url_for("dashboard"))
    return render_template("add_task.html",title="Add Task",name=name,status='add_task',submit_url=url_for('add_task'), streak=session['streak'])

#!#! need flash and finishing
@app.route('/quickadd',methods=['POST'])
@login_required
def quickadd():
    try:
        remaining=Task.query.filter_by(user_id=session['user_id'],milestone_id=None).count()
        prompt=request.form.get('quickadd_prompt')
        tasks=ai_models.quick_add(prompt)
        created_tasks=[]
        print(tasks)
        if not tasks:
            response = make_response("",200)
            response.headers['HX-Trigger'] = 'quick_add_error'
            return response
        for task in tasks:
            title=task['task']
            priority=task['priority']
            category=task['category']
            due_date=task['due_date']
            user_id=session['user_id']
            if category=='None':
                category=None
            if due_date=='None':
                due_date=None
            else:
                due_date=date.fromisoformat(due_date)
            new_task=Task(user_id=user_id,title=title, priority=priority, due_date=due_date, category=category,created_at=datetime.now(timezone.utc))
            db.session.add(new_task)
            for subtask in task.get("subtasks", []):
                subtask_title=subtask['subtask']
                subtask_priority=subtask['priority']
                subtask_due_date=subtask['due_date']
                if subtask_due_date=='None':
                    subtask_due_date=None
                else:
                    subtask_due_date=date.fromisoformat(subtask_due_date)
                new_subtask=SubTask(user_id=user_id,parent_task=new_task,title=subtask_title,priority=subtask_priority,due_date=subtask_due_date)
                db.session.add(new_subtask)
            db.session.add(new_task)
            created_tasks.append(new_task)
        db.session.commit()
        html_response=''
        if remaining==0:
            html_response+=f'''
            <div class="toolbar">
                <h3>Tasks</h3>
                <div class="dropdown">
                    <button class="menuu sortby"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M120-240v-80h240v80H120Zm0-200v-80h480v80H120Zm0-200v-80h720v80H120Z"/></svg><span>Sort by</span></button>
                    <div class="dropdown-content">
                        <a href="{ url_for('dashboard', sort='priority') }">Priority</a>
                        <a href="{ url_for('dashboard', sort='date') }">Due date</a>
                        <a href="{ url_for('dashboard', sort='name') }">Alphabetical</a>
                    </div> 
                </div>
            </div>
            <div class="delete-all-tasks">
                <a href="{ url_for('delete_all_tasks') }"  onclick="return confirm('Are you sure you want to delete all your tasks?')"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="m376-300 104-104 104 104 56-56-104-104 104-104-56-56-104 104-104-104-56 56 104 104-104 104 56 56Zm-96 180q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520Zm-400 0v520-520Z"/></svg><span>delete all tasks</span></a>
            </div>'''
        for task in created_tasks:
            html_response += f"<div class='task-card {task.priority.lower()}' id='task-{task.id}'><div class='card-header'>"
            html_response+=f"<p>{task.title}</p>"
            html_response+="<div class='dropdown'>"
            if task.evaluate:
                html_response+=f'''<a href="{url_for('break_down',task_id=task.id)}" class="break-down">Break down this task</a>'''
            html_response+=f'''<button class='menuu'>⋮</button>
                            <div class='dropdown-content'>
                            <a href="{ url_for('edit_task', task_id=task.id) }"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M200-200h57l391-391-57-57-391 391v57Zm-80 80v-170l528-527q12-11 26.5-17t30.5-6q16 0 31 6t26 18l55 56q12 11 17.5 26t5.5 30q0 16-5.5 30.5T817-647L290-120H120Zm640-584-56-56 56 56Zm-141 85-28-29 57 57-29-28Z"/></svg><span>Edit</span></a>
                            <a hx-post="{ url_for('complete_task',task_id=task.id) }" hx-target="#task-{task.id}" hx-swap="delete swap:200ms" hx-indicator="#spinner" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M382-240 154-468l57-57 171 171 367-367 57 57-424 424Z"/></svg><span>Complete</span></a>
                            <a href="{ url_for('add_subtask',task_id=task.id) }"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="m560-120-57-57 144-143H200v-480h80v400h367L503-544l56-57 241 241-240 240Z"/></svg><span>Add Subtask</span></a>
                            <a hx-delete="{ url_for('delete_task', task_id=task.id) }" hx-target="#task-{task.id}" hx-swap="delete swap:200ms"  hx-confirm="Are you sure you want to delete this task?" hx-indicator="#spinner" class="" ><svg xmlns="http://www.w3.org/2000/svg" height="24" viewBox="0 -960 960 960" width="24"><path d="M280-120q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520ZM360-280h80v-360h-80v360Zm160 0h80v-360h-80v360Z"/></svg><span>Delete</span></a></div></div></div><hr>
                '''
            html_response += f"<div class='task-title'>"
            html_response += '<div class="d-flex flex-wrap align-items-center gap-3 mt-2">'
            if task.due_date:
                html_response+=f'''<span class="badge bg-light text-secondary border d-inline-flex align-items-center gap-1 py-1.5 px-2.5 rounded-pill" style="font-size: 0.8rem;"><i class="bi bi-calendar-event"></i><strong>Due date: </strong>{ task.friendly_date }</span>
                                    <span class="text-muted d-none d-sm-inline">•</span>'''
            if task.category:
                html_response+=f'''<span class="badge bg-secondary-subtle text-secondary border border-secondary-subtle d-inline-flex align-items-center gap-1 py-1.5 px-2.5 rounded-pill"><i class="bi bi-tag"></i><strong>Category: </strong>{ task.category }</span>
                                    <span class="text-muted d-none d-sm-inline">•</span>'''
            if task.priority.lower() == 'high':
                html_response += f'''<span class="badge bg-danger-subtle text-danger border border-danger-subtle d-inline-flex align-items-center gap-1 py-1.5 px-2.5 rounded-pill" style="font-size: 0.8rem;">
                                        <span class="rounded-circle bg-danger" style="width: 6px; height: 6px;"></span>
                                        High Priority
                                    </span>'''
            elif task.priority.lower() == 'medium':
                html_response += f'''<span class="badge bg-warning-subtle text-warning-emphasis border border-warning-subtle d-inline-flex align-items-center gap-1 py-1.5 px-2.5 rounded-pill" style="font-size: 0.8rem;">
                                        <span class="rounded-circle bg-warning" style="width: 6px; height: 6px;"></span>
                                        Medium Priority
                                    </span>'''
            else:
                html_response += f'''<span class="badge bg-success-subtle text-success border border-success-subtle d-inline-flex align-items-center gap-1 py-1.5 px-2.5 rounded-pill" style="font-size: 0.8rem;">
                                        <span class="rounded-circle bg-success" style="width: 6px; height: 6px;"></span>
                                        Low Priority
                                    </span>'''
            if task.subtasks:
                html_response+='<button class="toggle-arrow collapsed" onclick="toggleSubtasks(this)"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M480-528 296-344l-56-56 240-240 240 240-56 56-184-184Z"/></svg></button>'
            html_response+='</div></div></div>'
            html_response+=f'''<ul class="subtask-tree hide-subtasks" id="subtasks-{task.id}">'''
            for  subtask in task.subtasks:
                html_response+=f'''<li><div class="task-card {subtask.priority.lower()} id="task-{subtask.id}"><div class="card-header">'''
                html_response += f"<p>{ subtask.title }</p>"
                html_response += f'''<div class="dropdown">
                                                <button class="menuu">⋮</button>
                                                <div class="dropdown-content">
                                                    <a href="{ url_for('edit_subtask', subtask_id=subtask.id) }"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M200-200h57l391-391-57-57-391 391v57Zm-80 80v-170l528-527q12-11 26.5-17t30.5-6q16 0 31 6t26 18l55 56q12 11 17.5 26t5.5 30q0 16-5.5 30.5T817-647L290-120H120Zm640-584-56-56 56 56Zm-141 85-28-29 57 57-29-28Z"/></svg><span>Edit</span></a>
                                                    <a hx-post="{ url_for('complete_subtask',subtask_id=subtask.id) }" hx-target="#subtask-{ subtask.id }" hx-swap="delete swap:200ms" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M382-240 154-468l57-57 171 171 367-367 57 57-424 424Z"/></svg><span>Complete</span></a>
                                                    <a hx-delete="{ url_for('delete_subtask', subtask_id=subtask.id) }" hx-target="#subtask-{ subtask.id }" hx-swap="delete swap:200ms"  hx-confirm="Are you sure you want to delete this subtask?" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24" viewBox="0 -960 960 960" width="24"><path d="M280-120q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520ZM360-280h80v-360h-80v360Zm160 0h80v-360h-80v360Z"/></svg><span>Delete</span></a>
                                                </div>
                                            </div>

                                        </div><hr>'''
                html_response += '<div class="task-title"><div class="d-flex flex-wrap align-items-center gap-3 mt-2">'
                if subtask.due_date:
                    html_response+=f'''<span class="badge bg-light text-secondary border d-inline-flex align-items-center gap-1 py-1.5 px-2.5 rounded-pill" style="font-size: 0.8rem;"><i class="bi bi-calendar-event"></i><strong>Due date: </strong>{ subtask.friendly_date }</span>
                                                    <span class="text-muted d-none d-sm-inline">•</span>'''
                if subtask.category:
                    html_response+=f'''<span class="badge bg-secondary-subtle text-secondary border border-secondary-subtle d-inline-flex align-items-center gap-1 py-1.5 px-2.5 rounded-pill"><i class="bi bi-tag"></i><strong>Category: </strong>{ task.category }</span>
                                                    <span class="text-muted d-none d-sm-inline">•</span>'''
                if subtask.priority.lower() == 'high':
                    html_response += '''<span class="badge bg-danger-subtle text-danger border border-danger-subtle d-inline-flex align-items-center gap-1 py-1.5 px-2.5 rounded-pill" style="font-size: 0.8rem;">
                                                            <span class="rounded-circle bg-danger" style="width: 6px; height: 6px;"></span>
                                                            High Priority
                                                        </span>'''
                elif subtask.priority.lower() == 'medium':
                    html_response += '''<span class="badge bg-warning-subtle text-warning-emphasis border border-warning-subtle d-inline-flex align-items-center gap-1 py-1.5 px-2.5 rounded-pill" style="font-size: 0.8rem;">
                                                            <span class="rounded-circle bg-warning" style="width: 6px; height: 6px;"></span>
                                                            Medium Priority
                                                        </span>'''
                else:
                    html_response += '''<span class="badge bg-success-subtle text-success border border-success-subtle d-inline-flex align-items-center gap-1 py-1.5 px-2.5 rounded-pill" style="font-size: 0.8rem;">
                                                            <span class="rounded-circle bg-success" style="width: 6px; height: 6px;"></span>
                                                            Low Priority
                                                        </span>'''
                html_response += '</div></div></div></li>'
            html_response+='</ul>'
        return html_response,200
    except:
        db.session.rollback()
        return "",404


@app.route('/add_subtask/<task_id>',methods=["POST",'GET'])
@login_required
def add_subtask(task_id):
    name = session['name']
    if request.method=="POST":
        try:
            parent_task=Task.query.filter_by(user_id=session['user_id'],id=task_id).first_or_404()
            task = request.form["task"]
            priority = request.form["priority"]
            due_date = request.form["due_date"]
            category= request.form["category"]
            user_id=session["user_id"]
            if not category:
                category=None
            if due_date:
                due_date=date.fromisoformat(due_date)
            else:
                due_date=None
            new_subtask = SubTask(parent_task=parent_task,title=task,priority=priority,category=category,due_date=due_date,user_id=user_id)
            db.session.add(new_subtask)
            db.session.commit()
            flash('SubTask added successfully!','success')
        except:
            flash(f"Something went wrong", "error")
            db.session.rollback()
        return redirect(url_for('dashboard'))
    return render_template("add_task.html",title="Add Subtask",name=name,submit_url=url_for("add_subtask",task_id=task_id),streak=session['streak'])

@app.route('/edit/<int:task_id>', methods=['GET','POST'])
@login_required
def edit_task(task_id):
    name = session['name']
    task=Task.query.filter_by(id=task_id,user_id=session["user_id"]).first_or_404()
    if request.method=="POST":
        try:
            updated_task=request.form["task"]
            task.title=updated_task
            task.priority=request.form['priority']
            category=request.form['category']
            if not category:
                category =ai_models.determinate_category(updated_task)
                if category == 'None':
                    category=None
            task.category=category
            due_date=request.form['due_date']
            if due_date:
                from datetime import date
                task.due_date = date.fromisoformat(due_date)
            else:
                task.due_date = None
            if not task.subtasks:
                evaluate=ai_models.evaluate_task(updated_task)
                task.evaluate=False
                if evaluate=="yes":
                    task.evaluate=True
            db.session.commit()
            flash("Task updated successfully!", "success")
        except :
            flash("Something went wrong", "error")
            db.session.rollback()
        return redirect(url_for("dashboard"))
    return render_template("add_task.html", title='Edit Task',task=task,name=name,submit_url=url_for('edit_task',task_id=task.id),streak=session['streak'])

@app.route('/edit_suggestion_task/<task_id>/<_id_>',methods=['POST','GET'])
@login_required
def edit_suggestion_task(task_id,_id_):
    name = session['name']
    task=Task.query.filter_by(id=task_id,user_id=session["user_id"]).first_or_404()
    if request.method=="POST":
        try:
            user = User.query.get(session["user_id"])
            name=user.name
            task=AISuggestions.query.filter_by(id=task_id,user_id=session["user_id"]).first_or_404()
            task.title=request.form["task"]
            task.priority=request.form['priority']
            task.category=request.form['category']
            due_date=request.form['due_date']
            if due_date:
                from datetime import date
                task.due_date = date.fromisoformat(due_date)
            else:
                task.due_date = None
            db.session.commit()
            flash("Task updated successfully!", "success")
            tasks=AISuggestions.query.filter_by(user_id=session["user_id"])
        except Exception:
            flash("Something went wrong", "error")
            db.session.rollback()
        return render_template("ai_suggestions.html",title="suggestions",tasks=tasks,id=_id_,name=name)
    return render_template("add_task.html", title='Edit Task',task=task, id=_id_,name=name,submit_url=url_for('edit_suggestion_task',task_id=task.id,_id_=_id_),streak=session['streak'])

@app.route('/edit_subtask/<subtask_id>',methods=['POST','GET'])
@login_required
def edit_subtask(subtask_id):
    try:
        name = session['name']
        subtask=SubTask.query.filter_by(id=subtask_id,user_id=session["user_id"]).first_or_404()
        if request.method=="POST":
            try:
                subtask.title=request.form["task"]
                subtask.priority=request.form['priority']
                subtask.category=request.form['category']
                due_date=request.form['due_date']
                if due_date:
                    from datetime import date
                    subtask.due_date = date.fromisoformat(due_date)
                else:
                    subtask.due_date = None
                db.session.commit()
                flash("Subtask updated successfully!", "success")
            except Exception:
                flash("Something went wrong", "error")
                db.session.rollback()
            return redirect(url_for('dashboard'))
    except:
        pass
    return render_template("add_task.html",title='Edit Subtask', task=subtask,name=name,submit_url=url_for('edit_subtask',subtask_id=subtask.id), streak=session['streak'])

@app.route('/delete/<int:task_id>', methods=['DELETE'])
@login_required
def delete_task(task_id):
    try:
        task=Task.query.filter_by(id=task_id,user_id=session["user_id"]).first_or_404()
        db.session.delete(task)
        db.session.commit()
        remaining = Task.query.filter_by(user_id=session["user_id"],milestone_id=None).count()
        if request.headers.get('HX-Request'):
            if remaining==0:
                return f'''<main class="content" id="tasks-container" hx-swap-oob="true"><div class="no-tasks-message">
                <svg xmlns="http://www.w3.org/2000/svg" height="100px" viewBox="0 -960 960 960" width="100px" fill="#000000"><path d="M330-120 120-330v-300l210-210h300l210 210v300L630-120H330Zm27-195 123-123 123 123 42-42-123-123 123-123-42-42-123 123-123-123-42 42 123 123-123 123 42 42Zm-2 135h250l175-175v-250L605-780H355L180-605v250l175 175Zm125-300Z"/></svg>
                <h1>No active tasks.</h1>
                <a href="{ url_for('add_task') }" class="btn btn-info add_task"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#FFFFFF"><path d="M440-120v-320H120v-80h320v-320h80v320h320v80H520v320h-80Z"/></svg><span>Add Task</span></a>
                </div></main>''', 200
            return f'''<ul class="subtask-tree" id="subtasks-{task_id}" hx-swap-oob="delete"></ul>''',200
    except:
        db.session.rollback()
        if request.headers.get('HX-Request'):
            return "", 400
    return redirect(url_for("dashboard"))

@app.route("/delete_suggestion_task/<int:task_id>/<_id_>",methods=['DELETE'])
@login_required
def delete_suggestion_task(task_id,_id_):
    name = session['name']
    try:
        task = AISuggestions.query.filter_by(id=task_id, user_id=session["user_id"]).first_or_404()
        db.session.delete(task)
        db.session.commit()
        remaining = AISuggestions.query.filter_by(user_id=session['user_id']).count()
        if remaining == 0:
            return render_template('dashboard')
        if request.headers.get('HX-Request'):
            return "",200
    except:
        db.session.rollback()
        if request.headers.get('HX-Request'):
            return "",400
    return render_template("ai_suggestions.html",title="suggestions",tasks=tasks,id=_id_,name=name)


@app.route("/delete_completed_task/<int:task_id>",methods=['DELETE'])
@login_required
def delete_completed_task(task_id):
    try:
        task = CompletedTask.query.filter_by(id=task_id, user_id=session["user_id"]).first_or_404()
        db.session.delete(task)
        db.session.commit()
        remaining=CompletedTask.query.filter_by(user_id=session["user_id"]).count()
        if request.headers.get('HX-Request'):
            if remaining==0:
                return '<main class="content" id="completed-tasks-container" hx-swap-oob="true"><h2>No completed tasks</h2></main>'
            return "",200
    except :
        db.session.rollback()
        if request.headers.get('HX-Request'):
            return "",400
    return redirect(url_for("completed_tasks"))

@app.route("/delete_subtask/<int:subtask_id>",methods=['DELETE'])
@login_required
def delete_subtask(subtask_id):
    try:
        subtask = SubTask.query.filter_by(id=subtask_id, user_id=session["user_id"]).first_or_404()
        db.session.delete(subtask)
        db.session.commit()
        if request.headers.get('HX-Request'):
            return "",200
    except Exception:
        db.session.rollback()
        if request.headers.get('HX-Request'):
            return "",400
        
    return redirect(url_for("dashboard"))

@app.route('/delete_all')
@login_required
def delete_all_tasks():
    try:
        Task.query.filter_by(user_id=session["user_id"]).delete()
        db.session.commit()
        flash("All tasks deleted successfully!", "success")
    except Exception:
        flash(f"Something went wrong", "error")
        db.session.rollback()
    return redirect(url_for("dashboard"))

@app.route('/delete_all_completed_tasks')
@login_required
def delete_all_completed_tasks():
    try:
        CompletedTask.query.filter_by(user_id=session["user_id"]).delete()
        db.session.commit()
        flash("All tasks deleted successfully!", "success")
    except Exception:
        flash("Something went wrong", "error")
        db.session.rollback()
    return redirect(url_for("completed_tasks"))

@app.route('/complete_task/<int:task_id>', methods=['POST'])
@login_required
def complete_task(task_id):
    try:
        task = Task.query.filter_by(id=task_id,user_id=session["user_id"]).first_or_404()
        completed_task = CompletedTask(title=task.title,user_id=session["user_id"],completed_at=datetime.now(timezone.utc),category=task.category,priority=task.priority)
        db.session.add(completed_task)
        db.session.delete(task)
        user = User.query.filter_by(id=session['user_id']).first_or_404()
        #!!
        time_to_complete=(datetime.now(timezone.utc)-task.created_at.replace(tzinfo=timezone.utc)).total_seconds()/3600
        if user.weekly_completed_tasks == 0:
            user.average_completion_time=float(time_to_complete)
        else:
            current_total_time = user.average_completion_time*user.weekly_completed_tasks
            new_time = current_total_time + time_to_complete
            user.average_completion_time = new_time / (user.weekly_completed_tasks)
        user.weekly_completed_tasks+= 1
        user.total_completed_tasks += 1
        #!!
        if user.categories:
            current_categories = user.categories.copy()
            if task.category in current_categories:
                current_categories[task.category] += 1
            else:
                current_categories[task.category] = 1
            user.categories = current_categories
        else:
            user.categories = {task.category:1}
        #!!
        if user.priorities:
            priorities=user.priorities
            high=priorities['high']
            medium=priorities['medium']
            low=priorities['low']
            current_priorities={'high':high,'medium':medium,'low':low}
            current_priorities[task.priority.lower()]+=1
            user.priorities = dict(current_priorities)
        else:
            user.priorities={'high':0,'medium':0,'low':0}
        #!!
        db.session.commit()
        remaining = Task.query.filter_by(user_id=session["user_id"],milestone_id=None).count()
        if request.headers.get("HX-Request"):
            if remaining==0:
                return f'''<main class="content" id="tasks-container" hx-swap-oob="true"><div class="no-tasks-message">
                <svg xmlns="http://www.w3.org/2000/svg" height="100px" viewBox="0 -960 960 960" width="100px" fill="#000000"><path d="M330-120 120-330v-300l210-210h300l210 210v300L630-120H330Zm27-195 123-123 123 123 42-42-123-123 123-123-42-42-123 123-123-123-42 42 123 123-123 123 42 42Zm-2 135h250l175-175v-250L605-780H355L180-605v250l175 175Zm125-300Z"/></svg>
                <h1>No active tasks.</h1>
                <a href="{ url_for('add_task') }" class="btn btn-info add_task"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#FFFFFF"><path d="M440-120v-320H120v-80h320v-320h80v320h320v80H520v320h-80Z"/></svg><span>Add Task</span></a>
                </div></main>''', 200
            return f'''<ul class="subtask-tree" id="subtasks-{task_id}" hx-swap-oob="delete"></ul>''',200
    except:
        db.session.rollback()
        if request.headers.get("HX-Request"):
            return "",400
    return redirect(url_for("dashboard"))

@app.route('/complete_subtask/<int:subtask_id>',methods=['POST'])
@login_required
def complete_subtask(subtask_id):
    try:
        task=SubTask.query.filter_by(id=subtask_id,user_id=session["user_id"]).first_or_404()
        title = task.title
        completed_task = CompletedTask(title=title,user_id=session["user_id"],completed_at=datetime.now(timezone.utc),category=task.category,priority=task.priority)
        db.session.add(completed_task)
        db.session.delete(task)
        db.session.commit()
        if request.headers.get("HX-Request"):
            return "",200
    except:
            db.session.rollback()
            if request.headers.get("HX-Request"):
                return "",400
    return redirect(url_for("dashboard"))

@app.route('/completed')
@login_required
def completed_tasks():
    update_streak()
    try:
        name = session['name']
        purge_expired_tasks()
        tasks = CompletedTask.query.filter_by(user_id=session["user_id"]).all()
        for i in tasks:
            expiration_time = i.completed_at.replace(tzinfo=timezone.utc) + timedelta(hours=12)
            i.time_left = expiration_time - datetime.now(timezone.utc)
            total_seconds = int(i.time_left.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            i.formatted_time_left = f"{hours}H {minutes}min"
    except:
        flash("Something went wrong", "error")
        db.session.rollback()
    return render_template("completed.html", title="Completed Tasks", tasks=tasks, status="completed_tasks",name=name,streak=session['streak'])


@app.route('/break-down/<task_id>',methods=['GET','POST'])
@login_required
def break_down(task_id):
    try:
        name = session['name']
        AISuggestions.query.filter_by(user_id=session['user_id']).delete()
        task=Task.query.filter_by(user_id=session['user_id'],id=task_id).first_or_404()
        subtasks=ai_models.break_down_task(task.title)
        breaked_tasks=[]
        for subtask in subtasks:
            new_task = AISuggestions(title=subtask['subtask'],priority=subtask['priority'],due_date=None,user_id=session["user_id"])
            db.session.add(new_task)
            breaked_tasks.append(new_task)
            db.session.commit()
    except:
        flash('Something went wrong','error')
        db.session.rollback()
    return render_template("ai_suggestions.html",title="suggestions",tasks=breaked_tasks,id=task_id,name=name,streak=streak)

@app.route('/confirm-break-down/<task_id>')
@login_required
def confirm_break_down(task_id):
    try:
        suggestions = AISuggestions.query.filter_by(user_id=session["user_id"])
        parent_task=Task.query.filter_by(user_id=session['user_id'],id=task_id).first_or_404()
        for i in suggestions:
            new_subtask = SubTask(parent_task=parent_task,title=i.title,priority=i.priority,category=i.category,due_date=i.due_date,user_id=session["user_id"])
            db.session.add(new_subtask)
            db.session.delete(i)
        parent_task.evaluate=False
        suggestions.delete()
        db.session.commit()
        flash('SubTasks added successfully!','success')
    except:
            flash("Something went wrong", "error")
            db.session.rollback()
    return redirect(url_for('dashboard'))

@app.route('/cancel-break-down')
@login_required
def cancel_break_down():
    try:
        AISuggestions.query.filter_by(user_id=session["user_id"]).delete()
        db.session.commit()
    except:
        flash("Something went wrong", "error")
    return redirect(url_for('dashboard'))

@app.route('/statics')
@login_required
def statics():
    update_streak()
    try: 
        user=User.query.filter_by(id=session['user_id']).first_or_404()
        name = session['name']
        charts=[]
        statics=insights(user)
        try:
            summary = ai_models.sammary_generator(statics)
        except:
            summary = None
        category_labels=[]
        category_values=[]
        user_categories = user.categories
        category_labels = [i for i in user_categories.keys()]
        category_values = [i for i in user_categories.values()]
        charts.append({'id':'categorychart','title':'Categories Distribution','labels':category_labels,'values':category_values,'type':'doughnut','indexAxis':'x'})
        priority_labels=['High','Medium','Low']
        priority_values=[value for value in statics['Count completed tasks by priority'].values()]
        charts.append({'id':'prioritychart','title':'Priority Distribution','labels':priority_labels,'values':priority_values,'type':'bar','indexAxis':'y'})
    except Exception as e:
        print(f"Error: {e}")
    return render_template('statics.html', title="Statics",charts=charts, statics=statics, status='statics', summary=summary, name=name,streak=session['streak'])

#!#! Projects sectiion 
@app.route('/projects')
@login_required
def projects():
    update_streak()
    try:
        name = session['name']
        projects = Project.query.filter_by(user_id=session['user_id']).all()
    except Exception as e:
        print(f"Error: {e}")
    return render_template("projects/projects.html", projects=projects, name=name, title="Projects", streak=session['streak'])
        
@app.route('/project/<int:project_id>')
@login_required
def project(project_id):
    try:
        name = session['name']
        project = Project.query.filter_by(user_id=session['user_id'],id=project_id).first_or_404()
    except Exception as e:
        print(f"Error: {e}")
    return render_template('projects/project.html',title=project.title, name=name, project=project, status="projects", streak=session['streak'])

@app.route('/projects/new',methods=['POST','GET'])
@login_required
def add_project():
    name = session['name']
    if request.method == 'POST':
        try:
            title = request.form.get('title')
            description = request.form.get('description')
            color = request.form.get('color')
            goal = request.form.get('goal')
            target_date = request.form.get('target_day')
            if target_date:
                target_date=date.fromisoformat(target_date)
            else:
                target_date = None
            new_project = Project(user_id=session['user_id'],title=title, description=description, color=color, goal=goal)
            db.session.add(new_project)
            db.session.commit()
            flash("Project added successfully","success")
        except:
            db.session.rollback()
            flash("Something went wrong","error")
        return redirect(url_for("project",project_id=new_project.id))
    return render_template('projects/add_project.html', title='Add Project',name=name, submit_url=url_for("add_project"), streak=session['streak'])

@app.route('/project/ai/new', methods=['POST'])
@login_required
def quick_add_project():
    try:
        title = request.form.get('title')
        description = request.form.get('description')
        color = request.form.get('color')
        goal = request.form.get('goal')
        target_date = request.form.get('target_day')
        if target_date:
            target_date = date.fromisoformat(target_date)
        else:
            target_date = None
        ai_project = ai_models.project_creator({'title':title,'goal':goal,'description':description,'target date':target_date if target_date else 'None'})
        if ai_project != 'None':
            title = ai_project['title']
            goal = ai_project['goal']
            description = ai_project['description']
            if not target_date:
                target_date = ai_project['target_date']
                if target_date != 'None':
                    target_date = date.fromisoformat(target_date)
                else:
                    target_date = None
            new_project = Project(user_id=session['user_id'], color=color, title=title, goal=goal, description=description, target_date=target_date)
            db.session.add(new_project)
            for milestone in ai_project['milestones']:
                title = milestone['title']
                new_milestone = Milestone(user_id=session['user_id'], project=new_project, title=title)
                db.session.add(new_milestone)
                for task in milestone['tasks']:
                    new_task = Task(user_id=session['user_id'], milestone=new_milestone, title=task)
                    db.session.add(new_task)
            db.session.commit()
            return redirect(url_for('project', project_id=new_project.id))
        else:
            flash('Cannot fulfill this request', 'error')
            return redirect(url_for('add_project'))
    except:
        db.session.rollback()
        return redirect(url_for('add_project'),404)

@app.route('/project/<int:project_id>/milestone/new', methods=['POST'])
@login_required
def add_milestone(project_id):
    try:
        title = request.form['title']
        new_milestone = Milestone(user_id=session['user_id'],project_id=project_id, title=title)
        project = Project.query.filter_by(user_id=session['user_id'], id=project_id).first_or_404()
        project.updated_at = datetime.now(timezone.utc)
        db.session.add(new_milestone)
        db.session.commit()
        html_response = ''
        html_response += f'''<div style="border:1px solid {project.color}" class="milestone-container" id="milestone-{new_milestone.id}"> <div class="milestone-header"> <div class="title-wrapper">
                        <div id="edit-milestone-title-{new_milestone.id}">
                            <span class="milestone-title" id="milestone-title-{new_milestone.id}">{ title }</span>
                            <form hx-post="{url_for('edit_milestone', milestone_id=new_milestone.id)}" hx-target="#edit-milestone-title-{new_milestone.id}" hx-indicator="#spinner" class="add-section" id=milestone-title-form-{new_milestone.id}>
                                <input type="text" name="title" placeholder="{title}" required>
                                <div class="form-buttons">
                                    <button type="submit"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#000000"><path d="M382-240 154-468l57-57 171 171 367-367 57 57-424 424Z"/></svg></button>
                                    <button type="button" onclick="cancelEditTitle({new_milestone.id})"><svg xmlns="http://www.w3.org/2000/svg" height="27px" viewBox="0 -960 960 960" width="27px" fill="#000000"><path d="m336-280-56-56 144-144-144-143 56-56 144 144 143-144 56 56-144 143 144 144-56 56-143-144-144 144Z"/></svg></button>
                                </div>
                            </form>
                        </div>
                        <div class="dropdown">
                            <button class="menuu">⋮</button>
                            <div class="dropdown-content" id="milestone-{new_milestone.id}-dropdown-content">
                                <a onclick="EditMilestoneTitle({new_milestone.id})" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M200-200h57l391-391-57-57-391 391v57Zm-80 80v-170l528-527q12-11 26.5-17t30.5-6q16 0 31 6t26 18l55 56q12 11 17.5 26t5.5 30q0 16-5.5 30.5T817-647L290-120H120Zm640-584-56-56 56 56Zm-141 85-28-29 57 57-29-28Z"/></svg><span>Edit Title</span></a>
                                <a hx-delete="{ url_for('delete_milestone', milestone_id=new_milestone.id) }" hx-target="#milestone-{ new_milestone.id }" hx-swap="delete swap:200ms"  hx-confirm="Please confirm the deleting?" hx-indicator="#spinner" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24" viewBox="0 -960 960 960" width="24"><path d="M280-120q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520ZM360-280h80v-360h-80v360Zm160 0h80v-360h-80v360Z"/></svg><span>Delete</span></a>
                            </div>
                        </div></div> <button class="toggle-arrow collapsed" onclick="toggletasks(this)"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M480-528 296-344l-56-56 240-240 240 240-56 56-184-184Z"/></svg></button></div>'''
        html_response += f'''<div class="progress-container" id="milestone-progress-container-{new_milestone.id}"> <div class="progress-label"> <strong>progress: </strong> <span>0.0%</span> </div> <div class="progress-bar-bg"> <div class="progress-bar-fill" style="width: 0%;"></div></div></div>'''
        html_response += f'''<ul class="tasks-tree hide-tasks">
                                <a class="btn btn-secondary add-task" onclick="toggleTaskForm({new_milestone.id})"><svg xmlns="http://www.w3.org/2000/svg" height="18px" viewBox="0 -960 960 960" width="18px" fill="#000000"><path d="M440-120v-320H120v-80h320v-320h80v320h320v80H520v320h-80Z"/></svg><span>New task</span></a>
                                <div class="add-section" id="task-form-{ new_milestone.id }">
                                    <form hx-post="{ url_for('add_milestone_task', milestone_id=new_milestone.id) }" hx-target="#tasks-{ new_milestone.id }" hx-swap="beforeend" hx-on::after-request="this.reset(); this.parentElement.style.display='none'" hx-indicator="#spinner">
                                        <input type="text" name="task" required>
                                        <div class="form-buttons">
                                            <button type="submit"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#000000"><path d="M382-240 154-468l57-57 171 171 367-367 57 57-424 424Z"/></svg></button>
                                            <button type="button" onclick="CancelAddTask({new_milestone.id})"><svg xmlns="http://www.w3.org/2000/svg" height="27px" viewBox="0 -960 960 960" width="27px" fill="#000000"><path d="m336-280-56-56 144-144-144-143 56-56 144 144 143-144 56 56-144 143 144 144-56 56-143-144-144 144Z"/></svg></button>
                                        </div>
                                    </form>
                                </div>
                                <div id="tasks-{new_milestone.id}"></div>
                                </ul></div>'''
        return html_response,200
    except:
        db.session.rollback()
        return "",404

@app.route('/milestone/<int:milestone_id>/task/new', methods=['POST'])
@login_required
def add_milestone_task(milestone_id):
    html_response = ''
    try:
        task = request.form['task']
        new_task = Task(user_id=session['user_id'], milestone_id=milestone_id, title=task)
        db.session.add(new_task)
        total_tasks = Task.query.filter_by(user_id=session['user_id'], milestone_id=milestone_id).count()
        total_completed_tasks = Task.query.filter_by(user_id=session['user_id'], milestone_id=milestone_id, completed=True).count()
        progress = round((total_completed_tasks/total_tasks)*100,1)
        milestone = Milestone.query.filter_by(user_id=session['user_id'], id=milestone_id).first_or_404()
        milestone.progress = progress
        total_tasks = 0
        total_completed_tasks = 0
        project = milestone.project
        for i in project.milestones:
            current_tasks = i.tasks
            total_tasks += len(current_tasks)
            total_completed_tasks += sum(1 for i in current_tasks if i.completed)
        project_progress = round((total_completed_tasks/total_tasks)*100,1)
        project.progress = project_progress
        project.updated_at = datetime.now(timezone.utc)
        color = project.color
        db.session.commit()
        html_response += f'''<div class="dropdown-content" id="milestone-{milestone_id}-dropdown-content" hx-swap-oob="true">
                                <a id="complete-milestone-{milestone_id}" hx-post="{ url_for('complete_milestone', milestone_id=milestone_id) }" hx-target="#milestone-{milestone_id}" onclick="return confirm('all tasks under this milestone will mark as completed')" hx-indicator="#spinner" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M382-240 154-468l57-57 171 171 367-367 57 57-424 424Z"/></svg><span>Complete</span></a>
                                <a onclick="EditMilestoneTitle({milestone_id})" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M200-200h57l391-391-57-57-391 391v57Zm-80 80v-170l528-527q12-11 26.5-17t30.5-6q16 0 31 6t26 18l55 56q12 11 17.5 26t5.5 30q0 16-5.5 30.5T817-647L290-120H120Zm640-584-56-56 56 56Zm-141 85-28-29 57 57-29-28Z"/></svg><span>Edit Title</span></a>
                                <a hx-delete="{ url_for('delete_milestone', milestone_id=milestone_id) }" hx-target="#milestone-{milestone_id}" hx-swap="delete swap:200ms" hx-confirm="Please confirm the deleting" hx-indicator="#spinner" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24" viewBox="0 -960 960 960" width="24"><path d="M280-120q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520ZM360-280h80v-360h-80v360Zm160 0h80v-360h-80v360Z"/></svg><span>Delete</span></a>
                            </div>'''
        html_response += f'''
        <li class="task" id="task-{new_task.id}"> <div class="task-wrapper">
        <div><input type="checkbox" name="{ new_task.id }" value="true" hx-post="{url_for('check_task', milestone_id=milestone_id, task_id=new_task.id)}" hx-trigger="change" hx-target="#task-{new_task.id}" hx-indicator="#spinner"><span class="task-title">{task}</span></div>
        <button hx-delete="{url_for('delete_milestone_task',task_id=new_task.id)}" hx-target="#task-{new_task.id}" hx-swap="delete swap:200ms" hx-confirm="Are you sure you want to delete this task" hx-indicator="#spinner" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#000000"><path d="M280-120q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520ZM360-280h80v-360h-80v360Zm160 0h80v-360h-80v360ZM280-720v520-520Z"/></svg></button>
        </div></li>
        <div class="progress-container" id="milestone-progress-container-{milestone_id}" hx-swap-oob="true">
        <div class="progress-label"><strong>progress: </strong><span>{progress}%</span></div>
        <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: {progress}%; background-color:{color}"></div></div></div>'''
        html_response += f''' <div class="progress-container" id="project-progress-container-{project.id}" hx-swap-oob="true">
                            <div class="progress-label"><strong>progress: </strong><span>{project_progress}%</span></div>
                            <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: {project_progress}%; background-color:{color}"></div></div></div>'''
        return html_response,200
    except:
        db.session.rollback()
        return "",404


@app.route('/project/<int:project_id>/edit', methods=['POST','GET'])
@login_required
def edit_project(project_id):
    name = session['name']
    project = Project.query.filter_by(user_id=session['user_id'], id=project_id).first_or_404()
    if request.method == 'POST':
        try:
            project.title = request.form['title']
            project.description = request.form['description']
            project.color = request.form['color']
            project.goal = request.form['goal']
            target_date = request.form['target_day']
            if target_date:
                project.target_date=date.fromisoformat(target_date)
            else:
                project.target_date = None
            db.session.commit()
            flash('Project updated successfully',"success")
            return redirect(url_for("project",project_id=project_id))
        except:
            db.session.rollback()
            flash("Something went wrong", "error")
    return render_template('projects/add_project.html', title="Edit Project",name=name,project=project, submit_url=url_for("edit_project",project_id=project_id),streak=session['streak'])

@app.route('/milestone/<int:milestone_id>/edit', methods=['POST'])
@login_required
def edit_milestone(milestone_id):
    try:
        milestone = Milestone.query.filter_by(user_id=session['user_id'], id=milestone_id).first_or_404()
        title = request.form['title']
        milestone.title = title
        db.session.commit()
        html_response = f'''<span class="milestone-title" id="milestone-title-{milestone_id}">{ title }</span>
                            <form hx-post="{ url_for('edit_milestone', milestone_id=milestone_id) }" hx-target="#edit-milestone-title-{milestone_id}" hx-indicator="#spinner" class="add-section" id="milestone-title-form-{milestone_id}">
                                <input type="text" name="title" placeholder="title" required>
                                <div class="form-buttons">
                                    <button type="submit"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#000000"><path d="M382-240 154-468l57-57 171 171 367-367 57 57-424 424Z"/></svg></button>
                                    <button type="button" onclick="CancelEditTitle({milestone_id})"><svg xmlns="http://www.w3.org/2000/svg" height="27px" viewBox="0 -960 960 960" width="27px" fill="#000000"><path d="m336-280-56-56 144-144-144-143 56-56 144 144 143-144 56 56-144 143 144 144-56 56-143-144-144 144Z"/></svg></button>
                                </div>
                            </form>'''
        return html_response,200
    except:
        db.session.rollback()
        return '',404

@app.route('/project/<int:project_id>/complete')
@login_required
def complete_project(project_id):
    try:
        project = Project.query.filter_by(user_id=session['user_id'], id=project_id).first_or_404()
        project.status = 'completed'
        project.progress = 100
        project.updated_at = datetime.now(timezone.utc)
        project.completed_at = datetime.now(timezone.utc)
        for milestone in project.milestones:
            milestone.progress = 100
            milestone.status = 'completed'
            for task in milestone.tasks:
                task.completed = True
        user = User.query.filter_by(id=session['user_id']).first_or_404()
        user.total_completed_projects += 1
        db.session.commit()
        return redirect(url_for('projects'))
    except:
        db.session.rollback()
        return "",404
@app.route('/project/<int:project_id>/active', methods=['POST'])
@login_required
def active_project(project_id):
    try:
        project = Project.query.filter_by(user_id=session['user_id'], id=project_id).first_or_404()
        project.updated_at = datetime.now(timezone.utc)
        project.status = 'active'
        db.session.commit()
        html_response = f'''<div class="status" id="project-{project_id}-status-container" hx-swap-oob="true">        
                                <span id="project-status" class="badge bg-success-subtle text-success border border-success-subtle d-inline-flex align-items-center gap-1 py-1.5 px-2.5 rounded-pill" style="font-size: 0.8rem;"><span class="rounded-circle bg-success" style="width: 6px; height: 6px;"></span>Active</span>
                                <div class="dropdown">
                                    <button class="menuu">⋮</button>
                                    <div class="dropdown-content">
                                         <a href="{ url_for('complete_project', project_id=project_id) }" onclick="if(confirm('please confirm the action: the project and all the tasks will mark as completed')) {{ sessionStorage.setItem('showConfetti', 'true'); return true; }} return false;"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M382-240 154-468l57-57 171 171 367-367 57 57-424 424Z"/></svg><span>Complete</span></a>
                                         <a href="{ url_for('edit_project', project_id=project_id) }"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M200-200h57l391-391-57-57-391 391v57Zm-80 80v-170l528-527q12-11 26.5-17t30.5-6q16 0 31 6t26 18l55 56q12 11 17.5 26t5.5 30q0 16-5.5 30.5T817-647L290-120H120Zm640-584-56-56 56 56Zm-141 85-28-29 57 57-29-28Z"/></svg><span>Edit</span></a>
                                         <a href="{ url_for('delete_project', project_id=project_id) }" onclick="return confirm('Are you sure you want to delete this project?')" ><svg xmlns="http://www.w3.org/2000/svg" height="24" viewBox="0 -960 960 960" width="24"><path d="M280-120q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520ZM360-280h80v-360h-80v360Zm160 0h80v-360h-80v360Z"/></svg><span>Delete</span></a>
                                    </div>
                                </div>
                            </div>'''
        return html_response,200
    except:
        db.session.rollback()
        return "",404

@app.route('/milestone/<int:milestone_id>/completed', methods=['POST'])
@login_required
def complete_milestone(milestone_id):
    html_response = ''
    try:
        milestone = Milestone.query.filter_by(user_id=session['user_id'], id=milestone_id).first_or_404()
        project = milestone.project
        milestone.progress = 100
        milestone.status = 'completed'
        for task in milestone.tasks:
            task.completed = True
        total_tasks = 0
        total_completed_tasks = 0
        for milestone in project.milestones:
            current_tasks = milestone.tasks
            total_tasks += len(current_tasks)
            total_completed_tasks += sum(1 for i in current_tasks if i.completed)
        project_progress = round((total_completed_tasks/total_tasks)*100,1)
        project.progress = project_progress
        project.updated_at = datetime.now(timezone.utc)
        if project_progress == 100.0 and project.status != 'completed':
            project.status = 'completed'
            user = User.query.filter_by(id=session['user_id']).first_or_404()
            user.total_completed_projects += 1
            html_response += f'''<div class="status" id="project-{project.id}-status-container" hx-swap-oob="true">        
                                <span id="project-status" class="badge bg-secondary-subtle text-secondary border border-secondary-subtle d-inline-flex align-items-center gap-1 py-2 px-3 rounded-pill" class="><i class="bi bi-tag"></i>Completed</span>
                                <div class="dropdown">
                                    <button class="menuu">⋮</button>
                                    <div class="dropdown-content">
                                         <a hx-post="{ url_for('active_project', project_id=project.id) }" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#000000"><path d="M621.5-338.5Q680-397 680-480t-58.5-141.5Q563-680 480-680t-141.5 58.5Q280-563 280-480t58.5 141.5Q397-280 480-280t141.5-58.5ZM480-80q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Zm0-80q134 0 227-93t93-227q0-134-93-227t-227-93q-134 0-227 93t-93 227q0 134 93 227t227 93Z"/></svg><span>Mark as active</span></a>
                                         <a href="{ url_for('edit_project', project_id=project.id) }"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M200-200h57l391-391-57-57-391 391v57Zm-80 80v-170l528-527q12-11 26.5-17t30.5-6q16 0 31 6t26 18l55 56q12 11 17.5 26t5.5 30q0 16-5.5 30.5T817-647L290-120H120Zm640-584-56-56 56 56Zm-141 85-28-29 57 57-29-28Z"/></svg><span>Edit</span></a>
                                         <a href="{ url_for('delete_project', project_id=project.id) }" onclick="return confirm('Are you sure you want to delete this project?')" ><svg xmlns="http://www.w3.org/2000/svg" height="24" viewBox="0 -960 960 960" width="24"><path d="M280-120q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520ZM360-280h80v-360h-80v360Zm160 0h80v-360h-80v360Z"/></svg><span>Delete</span></a>
                                    </div>
                                </div>
                            </div>
                            <script>
                                confetti({{
                                    particleCount: 100,
                                    spread: 70,
                                    origin: {{ y: 0.6 }}
                                }});
                            </script>'''
        html_response += f'''<div class="milestone-header"><div class="title-wrapper"><div class=""edit-milestone-title-{milestone_id}>
                             <span class="milestone-title-{milestone_id}">{milestone.title}</span>
                             <form hx-post="{url_for('edit_milestone',milestone_id=milestone_id)}" hx-tigger="change" hx-target="#edit-milestone-title-{milestone_id}" style="width:600px;" class="add-section" id="milestone-title-form-{milestone_id}">
                                <input type="text" name="title" placeholder="{milestone.title}" required>
                                <button type="submit"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#000000"><path d="M382-240 154-468l57-57 171 171 367-367 57 57-424 424Z"/></svg></button>
                                <button type="button" onclick="CancelEditTitle({milestone_id})"><svg xmlns="http://www.w3.org/2000/svg" height="27px" viewBox="0 -960 960 960" width="27px" fill="#000000"><path d="m336-280-56-56 144-144-144-143 56-56 144 144 143-144 56 56-144 143 144 144-56 56-143-144-144 144Z"/></svg></button>
                             </form>
                             </div>
                             <div class="dropdown">
                                <button class="menuu">⋮</button>
                                <div class="dropdown-content" id="milestone-{milestone_id}-dropdown-content">
                                    <a onclick="EditMilestoneTitle({milestone_id})" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M200-200h57l391-391-57-57-391 391v57Zm-80 80v-170l528-527q12-11 26.5-17t30.5-6q16 0 31 6t26 18l55 56q12 11 17.5 26t5.5 30q0 16-5.5 30.5T817-647L290-120H120Zm640-584-56-56 56 56Zm-141 85-28-29 57 57-29-28Z"/></svg><span>Edit Title</span></a>
                                    <a hx-delete="{ url_for('delete_milestone', milestone_id=milestone_id) }" hx-target="#milestone-{ milestone_id }" hx-swap="delete swap:200ms"  hx-confirm="Please confirm the deleting?" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24" viewBox="0 -960 960 960" width="24"><path d="M280-120q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520ZM360-280h80v-360h-80v360Zm160 0h80v-360h-80v360Z"/></svg><span>Delete</span></a>
                                </div>
                             </div>
                             </div>
                             <button class="toggle-arrow collapsed" onclick="toggletasks(this)"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M480-528 296-344l-56-56 240-240 240 240-56 56-184-184Z"/></svg></button>
                             </div>
                             <div class="progress-container" id="milestone-progress-container-{milestone_id}">
                                <div class="progress-label">
                                    <strong>progress: </strong>
                                    <span>100.0%</span>
                                </div>
                                <div class="progress-bar-bg">
                                    <div class="progress-bar-fill" style="width:100%; background-color: {project.color};"></div>
                                </div>
                            </div>'''
        html_response += f'''<ul class="tasks-tree hide-tasks">
                                <a class="btn btn-secondary add-task" onclick="toggleTaskForm({milestone_id})"><svg xmlns="http://www.w3.org/2000/svg" height="18px" viewBox="0 -960 960 960" width="18px" fill="#000000"><path d="M440-120v-320H120v-80h320v-320h80v320h320v80H520v320h-80Z"/></svg><span>New task</span></a>
                                <div id="tasks-{milestone_id}">'''
        for task in milestone.tasks:
            html_response += f'''<li class="task" id="task-{task.id}">
                                    <div class="task-wrapper">
                                        <div><input type="checkbox" value="true" hx-post="{url_for('uncheck_task', milestone_id=milestone_id, task_id=task.id)}" hx-trigger="change" hx-target="#task-{task.id}" checked><span>{task.title}</span></div>
                                        <button hx-delete="{{url_for('delete_milestone_task',task_id=task.id)}}" hx-target="#task-{{task.id}}" hx-swap="delete swap:200ms" hx-confirm="Are you sure you want to delete this task" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#000000"><path d="M280-120q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520ZM360-280h80v-360h-80v360Zm160 0h80v-360h-80v360ZM280-720v520-520Z"/></svg></button>
                                    </div>
                                 </li>'''
        html_response += f'''   </div>
                                <div class="add-section" id="task-form-{milestone_id}">
                                    <form hx-post="{url_for('add_milestone_task', milestone_id=milestone_id)}" hx-target="#tasks-{milestone_id}" hx-swap="beforeend" hx-on::after-request="this.reset(); this.parentElement.style.display='none'">
                                        <input type="text" name="task" required>
                                        <button type="submit"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#000000"><path d="M382-240 154-468l57-57 171 171 367-367 57 57-424 424Z"/></svg></button>
                                        <button type="button" onclick="CancelAddTask({milestone_id})"><svg xmlns="http://www.w3.org/2000/svg" height="27px" viewBox="0 -960 960 960" width="27px" fill="#000000"><path d="m336-280-56-56 144-144-144-143 56-56 144 144 143-144 56 56-144 143 144 144-56 56-143-144-144 144Z"/></svg></button>
                                    </form>
                                </div>
                                <div class="progress-container" id="project-progress-container-{project.id}" hx-swap-oob="true">
                                <div class="progress-label"><strong>progress: </strong><span>{project_progress}%</span></div>
                                <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: {project_progress}%; background-color:{project.color}"></div></div></div>'''
        html_response += "</ul>"
        db.session.commit()
        return html_response,200
    except:
        db.session.rollback()
        return '',404

@app.route('/project/<int:project_id>/delete', methods=['DELETE','GET'])
@login_required
def delete_project(project_id):
    try:
        project = Project.query.filter_by(user_id=session['user_id'],id=project_id).first_or_404()
        db.session.delete(project)
        db.session.commit()
        remaining = Project.query.filter_by(user_id=session['user_id']).count()
        if request.headers.get('HX-Request'):
            if remaining==0:
                return f'''<main class="content" id="projects-container" hx-swap-oob="true"><div class="no-projects-message">
                        <svg xmlns="http://www.w3.org/2000/svg" height="100px" viewBox="0 -960 960 960" width="100px" fill="#000000"><path d="M330-120 120-330v-300l210-210h300l210 210v300L630-120H330Zm27-195 123-123 123 123 42-42-123-123 123-123-42-42-123 123-123-123-42 42 123 123-123 123 42 42Zm-2 135h250l175-175v-250L605-780H355L180-605v250l175 175Zm125-300Z"/></svg>
                        <h2>No Projects</h2>
                        <a href="{ url_for('add_project') }" class="btn btn-info add_project"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#000000"><path d="M440-120v-320H120v-80h320v-320h80v320h320v80H520v320h-80Z"/></svg><span>Add a project</span></a>
                        </div></main>''', 200
            return "",200
        return redirect(url_for('projects'))
    except:
        db.session.rollback()
        if request.headers.get("HX-Request"):
            return "",400
    return redirect(url_for('projects'))

@app.route('/milestone/<int:milestone_id>/delete', methods=['DELETE'])
@login_required
def delete_milestone(milestone_id):
    try:
        milestone = Milestone.query.filter_by(user_id=session['user_id'],id=milestone_id).first_or_404()
        db.session.delete(milestone)
        project = milestone.project
        db.session.commit()
        total_tasks = 0
        total_completed_tasks = 0
        for i in project.milestones:
            current_tasks = i.tasks
            total_tasks += len(current_tasks)
            total_completed_tasks += sum(1 for i in current_tasks if i.completed)
        if total_tasks != 0:
            project_progress = round((total_completed_tasks/total_tasks)*100,1)
        else:
            project_progress = 0
        project.progress = project_progress
        project.updated_at = datetime.now(timezone.utc)
        color = project.color
        html_response = ''
        if project_progress == 100.0 and project.status != 'completed':
            project.status = 'completed'
            user = User.query.filter_by(id=session['user_id']).first_or_404()
            user.total_completed_project += 1
            html_response += f'''<div class="status" id="project-{project.id}-status-container" hx-swap-oob="true">        
                                    <span id="project-status" class="badge bg-secondary-subtle text-secondary border border-secondary-subtle d-inline-flex align-items-center gap-1 py-2 px-3 rounded-pill" class="><i class="bi bi-tag"></i>Completed</span>
                                    <div class="dropdown">
                                        <button class="menuu">⋮</button>
                                        <div class="dropdown-content">
                                            <a hx-post="{ url_for('active_project', project_id=project.id) }" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#000000"><path d="M621.5-338.5Q680-397 680-480t-58.5-141.5Q563-680 480-680t-141.5 58.5Q280-563 280-480t58.5 141.5Q397-280 480-280t141.5-58.5ZM480-80q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Zm0-80q134 0 227-93t93-227q0-134-93-227t-227-93q-134 0-227 93t-93 227q0 134 93 227t227 93Z"/></svg><span>Mark as active</span></a>
                                            <a href="{ url_for('edit_project', project_id=project.id) }"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M200-200h57l391-391-57-57-391 391v57Zm-80 80v-170l528-527q12-11 26.5-17t30.5-6q16 0 31 6t26 18l55 56q12 11 17.5 26t5.5 30q0 16-5.5 30.5T817-647L290-120H120Zm640-584-56-56 56 56Zm-141 85-28-29 57 57-29-28Z"/></svg><span>Edit</span></a>
                                            <a href="{ url_for('delete_project', project_id=project.id) }" onclick="return confirm('Are you sure you want to delete this project?')" ><svg xmlns="http://www.w3.org/2000/svg" height="24" viewBox="0 -960 960 960" width="24"><path d="M280-120q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520ZM360-280h80v-360h-80v360Zm160 0h80v-360h-80v360Z"/></svg><span>Delete</span></a>
                                        </div>
                                    </div>
                                </div>'''
        html_response += f''' <div class="progress-container" id="project-progress-container-{project.id}" hx-swap-oob="true">
                                <div class="progress-label"><strong>progress: </strong><span>{project_progress}%</span></div>
                                <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: {project_progress}%; background-color:{color}"></div></div></div>'''
        db.session.commit()
        return html_response,200
    except:
        db.session.rollback()
        return '',400
    
@app.route('/milestone/task/<int:task_id>/delete', methods=['DELETE'])
@login_required
def delete_milestone_task(task_id):
    try:
        html_response = ''
        task = Task.query.filter_by(user_id=session['user_id'], id=task_id).first_or_404()
        db.session.delete(task)
        milestone = task.milestone
        db.session.commit()
        total_milestone_tasks = Task.query.filter_by(user_id=session['user_id'], milestone_id=milestone.id).count()
        total_milestone_completed_tasks = Task.query.filter_by(user_id=session['user_id'], milestone_id=milestone.id, completed=True).count()
        if total_milestone_tasks != 0:
            progress = round((total_milestone_completed_tasks/total_milestone_tasks)*100,1)
        else:
            progress = 0
        milestone = Milestone.query.filter_by(user_id=session['user_id'], id=milestone.id).first_or_404()
        milestone.progress = progress
        total_tasks = 0
        total_completed_tasks = 0
        project = milestone.project
        for i in project.milestones:
            current_tasks = i.tasks
            total_tasks += len(current_tasks)
            total_completed_tasks += sum(1 for i in current_tasks if i.completed)
        if total_tasks != 0:
            project_progress = round((total_completed_tasks/total_tasks)*100,1)
        else:
            project_progress = 0
        project.progress = project_progress
        project.updated_at = datetime.now(timezone.utc)
        if project_progress == 100.0 and project.status != 'completed':
            project.status = 'completed'
            user = User.query.filter_by(id=session['user_id']).first_or_404()
            user.total_completed_projects += 1
            html_response += f'''<div class="status" id="project-{project.id}-status-container" hx-swap-oob="true">        
                                <span id="project-status" class="badge bg-secondary-subtle text-secondary border border-secondary-subtle d-inline-flex align-items-center gap-1 py-2 px-3 rounded-pill" class="><i class="bi bi-tag"></i>Completed</span>
                                <div class="dropdown">
                                    <button class="menuu">⋮</button>
                                    <div class="dropdown-content">
                                         <a hx-post="{ url_for('active_project', project_id=project.id) }" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#000000"><path d="M621.5-338.5Q680-397 680-480t-58.5-141.5Q563-680 480-680t-141.5 58.5Q280-563 280-480t58.5 141.5Q397-280 480-280t141.5-58.5ZM480-80q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Zm0-80q134 0 227-93t93-227q0-134-93-227t-227-93q-134 0-227 93t-93 227q0 134 93 227t227 93Z"/></svg><span>Mark as active</span></a>
                                         <a href="{ url_for('edit_project', project_id=project.id) }"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M200-200h57l391-391-57-57-391 391v57Zm-80 80v-170l528-527q12-11 26.5-17t30.5-6q16 0 31 6t26 18l55 56q12 11 17.5 26t5.5 30q0 16-5.5 30.5T817-647L290-120H120Zm640-584-56-56 56 56Zm-141 85-28-29 57 57-29-28Z"/></svg><span>Edit</span></a>
                                         <a href="{ url_for('delete_project', project_id=project.id) }" onclick="return confirm('Are you sure you want to delete this project?')" ><svg xmlns="http://www.w3.org/2000/svg" height="24" viewBox="0 -960 960 960" width="24"><path d="M280-120q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520ZM360-280h80v-360h-80v360Zm160 0h80v-360h-80v360Z"/></svg><span>Delete</span></a>
                                    </div>
                                </div>
                            </div>'''
        color = project.color
        db.session.commit()
        html_response += f'''
                <div class="progress-container" id="milestone-progress-container-{milestone.id}" hx-swap-oob="true">
                <div class="progress-label"><strong>progress: </strong><span>{progress}%</span></div>
                <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: {progress}%; background-color:{color}"></div></div></div>'''
        html_response += f''' <div class="progress-container" id="project-progress-container-{project.id}" hx-swap-oob="true">
                                <div class="progress-label"><strong>progress: </strong><span>{project_progress}%</span></div>
                                <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: {project_progress}%; background-color:{color}"></div></div></div>'''
        return html_response,200
    except:
        return '',404


@app.route('/milestone/<int:milestone_id>/task/<int:task_id>/check',methods=['POST'])
@login_required
def check_task(milestone_id,task_id):
    html_response = ''
    try:
        task = Task.query.filter_by(user_id=session['user_id'], id=task_id).first_or_404()
        task.completed = True
        db.session.commit()
        total_milestone_tasks = Task.query.filter_by(user_id=session['user_id'], milestone_id=milestone_id).count()
        total_milestone_completed_tasks = Task.query.filter_by(user_id=session['user_id'], milestone_id=milestone_id, completed=True).count()
        progress = round((total_milestone_completed_tasks/total_milestone_tasks)*100,1)
        milestone = Milestone.query.filter_by(user_id=session['user_id'], id=milestone_id).first_or_404()
        milestone.progress = progress
        total_tasks = 0
        total_completed_tasks = 0
        project = milestone.project
        for i in project.milestones:
            current_tasks = i.tasks
            total_tasks += len(current_tasks)
            total_completed_tasks += sum(1 for i in current_tasks if i.completed)
        project_progress = round((total_completed_tasks/total_tasks)*100,1)
        project.updated_at = datetime.now(timezone.utc)
        project.progress = project_progress
        if project_progress == 100.0 and project.status != 'completed':
            project.status = 'completed'
            user = User.query.filter_by(id=session['user_id']).first_or_404()
            user.total_completed_projects += 1
            html_response += f'''<div class="status" id="project-{project.id}-status-container" hx-swap-oob="true">        
                                    <span id="project-status" class="badge bg-secondary-subtle text-secondary border border-secondary-subtle d-inline-flex align-items-center gap-1 py-2 px-3 rounded-pill" class="><i class="bi bi-tag"></i>Completed</span>
                                    <div class="dropdown">
                                        <button class="menuu">⋮</button>
                                        <div class="dropdown-content">
                                            <a hx-post="{ url_for('active_project', project_id=project.id) }" hx-indicator="#spinner" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#000000"><path d="M621.5-338.5Q680-397 680-480t-58.5-141.5Q563-680 480-680t-141.5 58.5Q280-563 280-480t58.5 141.5Q397-280 480-280t141.5-58.5ZM480-80q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Zm0-80q134 0 227-93t93-227q0-134-93-227t-227-93q-134 0-227 93t-93 227q0 134 93 227t227 93Z"/></svg><span>Mark as active</span></a>
                                            <a href="{ url_for('edit_project', project_id=project.id) }"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M200-200h57l391-391-57-57-391 391v57Zm-80 80v-170l528-527q12-11 26.5-17t30.5-6q16 0 31 6t26 18l55 56q12 11 17.5 26t5.5 30q0 16-5.5 30.5T817-647L290-120H120Zm640-584-56-56 56 56Zm-141 85-28-29 57 57-29-28Z"/></svg><span>Edit</span></a>
                                            <a href="{ url_for('delete_project', project_id=project.id) }" onclick="return confirm('Are you sure you want to delete this project?')" ><svg xmlns="http://www.w3.org/2000/svg" height="24" viewBox="0 -960 960 960" width="24"><path d="M280-120q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520ZM360-280h80v-360h-80v360Zm160 0h80v-360h-80v360Z"/></svg><span>Delete</span></a>
                                        </div>
                                    </div>
                                </div>
                            <script>
                                confetti({{
                                    particleCount: 400,
                                    spread: 100,
                                    origin: {{ y: 0.6 }}
                                }});
                            </script>'''
        color = project.color
        db.session.commit()
        if progress == 100.0:
            html_response += f'''<div class="dropdown-content" id="milestone-{milestone_id}-dropdown-content" hx-swap-oob="true">
                                    <a onclick="EditMilestoneTitle({milestone_id})" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M200-200h57l391-391-57-57-391 391v57Zm-80 80v-170l528-527q12-11 26.5-17t30.5-6q16 0 31 6t26 18l55 56q12 11 17.5 26t5.5 30q0 16-5.5 30.5T817-647L290-120H120Zm640-584-56-56 56 56Zm-141 85-28-29 57 57-29-28Z"/></svg><span>Edit Title</span></a>
                                    <a hx-delete="{ url_for('delete_milestone', milestone_id=milestone_id) }" hx-target="#milestone-{ milestone_id }" hx-swap="delete swap:200ms"  hx-confirm="Please confirm the deleting?" hx-indicator="#spinner" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24" viewBox="0 -960 960 960" width="24"><path d="M280-120q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520ZM360-280h80v-360h-80v360Zm160 0h80v-360h-80v360Z"/></svg><span>Delete</span></a>
                                </div>'''
        html_response += f'''<div class="task-wrapper">
        <div><input type="checkbox" name="{ task_id }" value="true" hx-post="{url_for('uncheck_task', milestone_id=milestone_id, task_id=task_id)}" hx-trigger="change" hx-target="#task-{task_id}" hx-indicator="#spinner" checked><span class="task-title">{task.title}</span></div>
        <button hx-delete="{url_for('delete_milestone_task',task_id=task_id)}" hx-target="#task-{task_id}" hx-swap="delete swap:200ms" hx-confirm="Are you sure you want to delete this task" hx-indicator="#spinner" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#000000"><path d="M280-120q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520ZM360-280h80v-360h-80v360Zm160 0h80v-360h-80v360ZM280-720v520-520Z"/></svg></button>
        </div>
        <div class="progress-container" id="milestone-progress-container-{milestone_id}" hx-swap-oob="true">
        <div class="progress-label"><strong>progress: </strong><span>{progress}%</span></div>
        <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: {progress}%; background-color:{color}"></div></div></div>'''
        html_response += f''' <div class="progress-container" id="project-progress-container-{project.id}" hx-swap-oob="true">
                                <div class="progress-label"><strong>progress: </strong><span>{project_progress}%</span></div>
                                <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: {project_progress}%; background-color:{color}"></div></div></div>'''
        return html_response,200
    except:
        db.session.rollback()
        return "",404
@app.route('/milestone/<int:milestone_id>/task/<int:task_id>/uncheck',methods=['POST'])
@login_required
def uncheck_task(milestone_id,task_id):
    try:
        task = Task.query.filter_by(user_id=session['user_id'], id=task_id).first_or_404()
        task.completed = False
        db.session.commit()
        total_milestone_tasks = Task.query.filter_by(user_id=session['user_id'], milestone_id=milestone_id).count()
        total_milestone_completed_tasks = Task.query.filter_by(user_id=session['user_id'], milestone_id=milestone_id, completed=True).count()
        progress = round((total_milestone_completed_tasks/total_milestone_tasks)*100,1)
        milestone = Milestone.query.filter_by(user_id=session['user_id'], id=milestone_id).first_or_404()
        milestone.progress = progress
        #!
        total_tasks = 0
        total_completed_tasks = 0
        project = milestone.project
        for i in project.milestones:
            current_tasks = i.tasks
            total_tasks += len(current_tasks)
            total_completed_tasks += sum(1 for i in current_tasks if i.completed)
        project_progress = round((total_completed_tasks/total_tasks)*100,1)
        project.progress = project_progress
        project.updated_at = datetime.now(timezone.utc)
        color = project.color
        db.session.commit()
        html_response = ''
        html_response += f'''<div class="dropdown-content" id="milestone-{milestone_id}-dropdown-content" hx-swap-oob="true">
                                <a hx-post="{ url_for('complete_milestone', milestone_id=milestone_id) }" hx-target="#milestone-{milestone_id}" onclick="return confirm('all tasks under this milestone will mark as completed')" hx-indicator="#spinner" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M382-240 154-468l57-57 171 171 367-367 57 57-424 424Z"/></svg><span>Complete</span></a>
                                <a onclick="EditMilestoneTitle({milestone_id})" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#e3e3e3"><path d="M200-200h57l391-391-57-57-391 391v57Zm-80 80v-170l528-527q12-11 26.5-17t30.5-6q16 0 31 6t26 18l55 56q12 11 17.5 26t5.5 30q0 16-5.5 30.5T817-647L290-120H120Zm640-584-56-56 56 56Zm-141 85-28-29 57 57-29-28Z"/></svg><span>Edit Title</span></a>
                                <a hx-delete="{ url_for('delete_milestone', milestone_id=milestone_id) }" hx-target="#milestone-{ milestone_id }" hx-swap="delete swap:200ms"  hx-confirm="Please confirm the deleting?" hx-indicator="#spinner" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24" viewBox="0 -960 960 960" width="24"><path d="M280-120q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520ZM360-280h80v-360h-80v360Zm160 0h80v-360h-80v360Z"/></svg><span>Delete</span></a>
                            </div>'''
        html_response += f'''<div class="task-wrapper">
        <div><input type="checkbox" name="{ task_id }" value="true" hx-post="{url_for('check_task', milestone_id=milestone_id, task_id=task_id)}" hx-trigger="change" hx-target="#task-{task_id}" hx-indicator="#spinner"><span class="task-title">{task.title}</span></div>
        <button hx-delete="{url_for('delete_milestone_task',task_id=task_id)}" hx-target="#task-{task_id}" hx-swap="delete swap:200ms" hx-confirm="Are you sure you want to delete this task" hx-indicator="#spinner" class=""><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#000000"><path d="M280-120q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520ZM360-280h80v-360h-80v360Zm160 0h80v-360h-80v360ZM280-720v520-520Z"/></svg></button>
        </div>
        <div class="progress-container" id="milestone-progress-container-{milestone_id}" hx-swap-oob="true">
        <div class="progress-label"><strong>progress: </strong><span>{progress}%</span></div>
        <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: {progress}%; background-color:{color}"></div></div></div>'''
        html_response += f'''<div class="progress-container" id="project-progress-container-{project.id}" hx-swap-oob="true">
                            <div class="progress-label"><strong>progress: </strong><span>{project_progress}%</span></div>
                            <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: {project_progress}%; background-color:{color}"></div></div></div>'''
        return html_response,200
    except:
        db.session.rollback()
        return "",404

@app.route("/pomodoro")
def pomodoro():
    return render_template('pomodoro.html')

@app.route("/logout")
def logout():
    if "user_id" not in session:
         return redirect(url_for("log_in"))
    session.clear()
    return redirect(url_for("home"))

#!#!#! reset the database if RESER_DB=="True", For your local using, you can just use:
#! with app.app_context():
#!    db.create_all()
with app.app_context():
    if os.environ.get("RESET_DB") == "True":
        db.drop_all()
        db.create_all()
    else:
        db.create_all()
if __name__ == "__main__":
    app.run(debug=True)
    # app.run(host="0.0.0.0", port=5000)
    print("================ Application Stoped ================")