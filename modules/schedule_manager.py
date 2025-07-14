import schedule
import asyncio
import logging
import traceback
from datetime import datetime

# 定义全局变量
attendance_system_global = None
last_job_check = None
last_job_count = 0
job_log_interval = 60  # 至少间隔60秒输出一次任务日志

async def run_schedule():
    global attendance_system_global, last_job_check, last_job_count
    startup_delay = True  # 启动时延迟输出详细日志

    while True:
        try:
            # 获取当前定时任务列表
            jobs = schedule.get_jobs()
            current_time = datetime.now()

            # 启动后延迟60秒再开始输出详细日志
            if startup_delay:
                if last_job_check is None:
                    last_job_check = current_time
                elif (current_time - last_job_check).total_seconds() > 60:
                    startup_delay = False

            # 只在任务数量变化或者每隔一段时间输出一次日志
            if (not startup_delay and jobs and (last_job_check is None or
                         (current_time - last_job_check).total_seconds() > job_log_interval or
                         len(jobs) != last_job_count)):
                logging.info(f"当前定时任务数量: {len(jobs)}")
                for i, job in enumerate(jobs):
                    logging.info(f"任务 #{i+1}: 下次运行时间: {job.next_run}, 任务函数: {job.job_func}")
                last_job_check = current_time
                last_job_count = len(jobs)

            # 运行待处理的定时任务
            for job in jobs:
                if job.should_run:
                    try:
                        # 只在任务实际执行时记录日志
                        current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        logging.info(f"[{current_time_str}] 开始执行定时任务")
                        # 执行任务并等待其完成
                        result = job.run()
                        if asyncio.iscoroutine(result):
                            await result
                        logging.info(f"[{current_time_str}] 定时任务执行完成")
                    except Exception as e:
                        error_msg = f"执行定时任务时发生错误: {str(e)}"
                        print(error_msg)
                        logging.error(error_msg)
                        logging.error(traceback.format_exc())

            # 执行心跳检测
            if attendance_system_global:
                # 每2小时检查一次打卡状态，避免过于频繁的检查
                current_hour = datetime.now().hour
                if datetime.now().minute == 0 and current_hour % 2 == 0:
                    await attendance_system_global.check_punch_status()

            await asyncio.sleep(1)
        except Exception as e:
            error_msg = f"调度任务发生错误: {str(e)}"
            print(error_msg)
            logging.error(error_msg)
            logging.error(traceback.format_exc())
            await asyncio.sleep(5)  # 发生错误时等待一段时间后继续